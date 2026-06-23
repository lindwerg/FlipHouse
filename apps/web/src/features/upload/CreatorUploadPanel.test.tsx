// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

// Drive the panel through a mocked useVideoUpload so the panel's wiring (flip on
// submit, phase/progress/error → HeroDropzone) is tested without fetch/Worker/tus.
const hookState = vi.hoisted(() => ({
  status: 'idle' as 'idle' | 'hashing' | 'uploading' | 'done' | 'error',
  progress: 0,
  error: null as string | null,
  contentHash: null as string | null,
  flip: vi.fn(),
}));

vi.mock('./useVideoUpload', () => ({
  useVideoUpload: () => hookState,
}));

// Drive the URL-ingest path through a mocked useUrlIngest so the panel's link
// wiring (submit on a link-only flip, status/error → HeroDropzone) is tested
// without a real fetch to /api/uploads/ingest.
const ingestState = vi.hoisted(() => ({
  status: 'idle' as 'idle' | 'submitting' | 'queued' | 'error',
  error: null as string | null,
  submit: vi.fn(),
}));

vi.mock('./useUrlIngest', () => ({
  useUrlIngest: () => ingestState,
}));

// ResultsView owns its own polling + fetch; stub it so the panel's wiring (mount
// only when a contentHash exists) is tested in isolation from the network.
const resultsViewMock = vi.hoisted(() => vi.fn());
vi.mock('@/features/results/ResultsView', () => ({
  ResultsView: (props: { contentHash: string }) => {
    resultsViewMock(props);
    return <div data-slot="results-view-stub">{props.contentHash}</div>;
  },
}));

const { CreatorUploadPanel } = await import('./CreatorUploadPanel');

function makeVideoFile(name = 'clip.mp4'): File {
  return new File(['x'], name, { type: 'video/mp4' });
}

function dropFileOn(element: Element, file: File): void {
  fireEvent.drop(element, {
    dataTransfer: {
      types: ['Files'],
      files: [file],
      items: [{ kind: 'file', type: file.type, getAsFile: () => file }],
    },
  });
}

afterEach(() => {
  hookState.status = 'idle';
  hookState.progress = 0;
  hookState.error = null;
  hookState.contentHash = null;
  hookState.flip = vi.fn();
  ingestState.status = 'idle';
  ingestState.error = null;
  ingestState.submit = vi.fn();
  vi.clearAllMocks();
});

describe('CreatorUploadPanel', () => {
  it('renders the hero dropzone for video upload', () => {
    render(<CreatorUploadPanel />);

    expect(screen.getByRole('region', { name: /загрузка видео/i })).toBeInTheDocument();
  });

  it('calls flip with the selected file on submit', async () => {
    render(<CreatorUploadPanel />);

    dropFileOn(screen.getByRole('button', { name: /перетащите/i }), makeVideoFile('vid.mp4'));
    await waitFor(() => expect(screen.getByText('vid.mp4')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /отправить/i }));

    await waitFor(() => expect(hookState.flip).toHaveBeenCalledTimes(1));
    expect(hookState.flip.mock.calls[0]![0]).toBeInstanceOf(File);
    expect((hookState.flip.mock.calls[0]![0] as File).name).toBe('vid.mp4');
  });

  it('does not call flip when submitting with no file (link-only is not yet supported)', async () => {
    render(<CreatorUploadPanel />);

    fireEvent.click(screen.getByRole('button', { name: /отправить/i }));

    // HeroDropzone shows its own validation alert; the panel never flips a
    // fileless payload (the upload path is file-only for P2.2).
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(hookState.flip).not.toHaveBeenCalled();
  });

  it('submits a link-only flip to the URL-ingest hook (server-side download)', async () => {
    render(<CreatorUploadPanel />);

    // A valid video link makes HeroDropzone fire onFlip with {url} (no file); the
    // panel routes it to the ingest hook (POST /api/uploads/ingest), NOT the file
    // upload hook.
    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: 'https://youtu.be/abc123' },
    });
    fireEvent.click(screen.getByRole('button', { name: /отправить/i }));

    await waitFor(() => expect(ingestState.submit).toHaveBeenCalledTimes(1));
    expect(ingestState.submit).toHaveBeenCalledWith('https://youtu.be/abc123');
    expect(hookState.flip).not.toHaveBeenCalled();
  });

  it('surfaces the URL-ingest queued caption after a link submit', () => {
    ingestState.status = 'queued';

    render(<CreatorUploadPanel />);

    // Before any submit the panel shows the dropzone idle; we assert the ingest
    // copy is wired by rendering with a queued ingest state AFTER a link submit.
    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: 'https://youtu.be/abc123' },
    });
    fireEvent.click(screen.getByRole('button', { name: /отправить/i }));

    expect(screen.getByText(/принято в работу/i)).toBeInTheDocument();
  });

  it('surfaces a URL-ingest error as a role=alert after a link submit', () => {
    ingestState.status = 'error';
    ingestState.error = 'YouTube заблокировал загрузку';

    render(<CreatorUploadPanel />);

    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: 'https://youtu.be/abc123' },
    });
    fireEvent.click(screen.getByRole('button', { name: /отправить/i }));

    expect(screen.getByRole('alert')).toHaveTextContent('YouTube заблокировал');
  });

  it('reflects the uploading phase and progress from the hook', () => {
    hookState.status = 'uploading';
    hookState.progress = 60;

    render(<CreatorUploadPanel />);

    const bar = screen.getByRole('progressbar', { name: /прогресс загрузки/i });

    expect(bar).toHaveAttribute('aria-valuenow', '60');
  });

  it('surfaces the hook error as a role=alert', () => {
    hookState.status = 'error';
    hookState.error = 'unauthenticated';

    render(<CreatorUploadPanel />);

    expect(screen.getByRole('alert')).toHaveTextContent('unauthenticated');
  });

  it('does not mount the results view before the file is hashed (no contentHash)', () => {
    render(<CreatorUploadPanel />);

    expect(resultsViewMock).not.toHaveBeenCalled();
  });

  it('mounts the inline results view with the contentHash once hashing completes', () => {
    hookState.contentHash = 'a'.repeat(64);

    render(<CreatorUploadPanel />);

    expect(resultsViewMock).toHaveBeenCalledWith({ contentHash: 'a'.repeat(64) });
    expect(screen.getByText('a'.repeat(64))).toBeInTheDocument();
  });
});
