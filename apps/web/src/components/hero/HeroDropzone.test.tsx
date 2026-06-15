// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { HeroDropzone } from './HeroDropzone';

function makeVideoFile(name = 'clip.mp4', size?: number): File {
  const file = new File(['x'], name, { type: 'video/mp4' });

  if (size !== undefined) {
    Object.defineProperty(file, 'size', { value: size });
  }

  return file;
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

const region = () => screen.getByRole('region', { name: /загрузка видео/i });
const dropBox = () => screen.getByRole('button', { name: /перетащите/i });
const submitButton = () => screen.getByRole('button', { name: /отправить/i });

afterEach(() => {
  vi.restoreAllMocks();
});

describe('HeroDropzone', () => {
  it('initial status is ready and submit is enabled', () => {
    render(<HeroDropzone />);

    expect(region()).toHaveAttribute('data-status', 'ready');
    expect(submitButton()).toBeEnabled();
  });

  it('dropping a video file shows a file chip and keeps status ready', async () => {
    render(<HeroDropzone />);

    dropFileOn(dropBox(), makeVideoFile('clip.mp4'));

    await waitFor(() => expect(screen.getByText('clip.mp4')).toBeInTheDocument());
    expect(region()).toHaveAttribute('data-status', 'ready');
  });

  it('rejects non-video file and sets status error', async () => {
    render(<HeroDropzone />);

    const png = new File(['x'], 'pic.png', { type: 'image/png' });
    dropFileOn(dropBox(), png);

    await waitFor(() => expect(region()).toHaveAttribute('data-status', 'error'));
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  it('rejects file over maxSize 500MB and sets status error', async () => {
    render(<HeroDropzone />);

    dropFileOn(dropBox(), makeVideoFile('big.mp4', 600 * 1024 * 1024));

    await waitFor(() => expect(region()).toHaveAttribute('data-status', 'error'));
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  it('pasting a valid video URL shows a link chip alongside file chip', async () => {
    const { container } = render(<HeroDropzone />);

    dropFileOn(dropBox(), makeVideoFile('clip.mp4'));
    await waitFor(() =>
      expect(container.querySelector('[data-slot="file-chip"]')).toHaveTextContent('clip.mp4'),
    );

    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: 'https://youtu.be/abc123' },
    });

    expect(container.querySelector('[data-slot="link-chip"]')).toHaveTextContent(
      'youtu.be/abc123',
    );
    expect(container.querySelector('[data-slot="file-chip"]')).toHaveTextContent('clip.mp4');
  });

  it('pasting a non-URL string does not create a link chip', () => {
    const { container } = render(<HeroDropzone />);

    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: 'hello world' },
    });

    expect(container.querySelector('[data-slot="link-chip"]')).toBeNull();
  });

  it('submit with neither file nor valid url sets status error and does not call onFlip', async () => {
    const onFlip = vi.fn();
    render(<HeroDropzone onFlip={onFlip} />);

    fireEvent.click(submitButton());

    await waitFor(() => expect(region()).toHaveAttribute('data-status', 'error'));
    expect(onFlip).not.toHaveBeenCalled();
  });

  it('submit with a file transitions ready→submitted→streaming and calls onFlip with the file', async () => {
    const onFlip = vi.fn();
    render(<HeroDropzone onFlip={onFlip} />);

    dropFileOn(dropBox(), makeVideoFile('clip.mp4'));
    await waitFor(() => expect(screen.getByText('clip.mp4')).toBeInTheDocument());

    fireEvent.click(submitButton());

    expect(region()).toHaveAttribute('data-status', 'submitted');
    await waitFor(() => expect(region()).toHaveAttribute('data-status', 'streaming'));

    expect(onFlip).toHaveBeenCalledTimes(1);
    const payload = onFlip.mock.calls[0]![0] as { file?: File; url?: string };
    expect(payload.file).toBeInstanceOf(File);
    expect(payload.file?.name).toBe('clip.mp4');
    expect(payload.url).toBeUndefined();
  });

  it('submit with a link calls onFlip with {url}', async () => {
    const onFlip = vi.fn();
    render(<HeroDropzone onFlip={onFlip} />);

    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: 'https://youtu.be/abc123' },
    });
    fireEvent.click(submitButton());

    await waitFor(() => expect(region()).toHaveAttribute('data-status', 'streaming'));
    expect(onFlip).toHaveBeenCalledTimes(1);
    expect(onFlip.mock.calls[0]![0]).toEqual({ url: 'https://youtu.be/abc123' });
  });

  it('globalDrop on the hero region routes the file into the box', async () => {
    render(<HeroDropzone />);

    dropFileOn(region(), makeVideoFile('clip.mp4'));

    await waitFor(() => expect(screen.getByText('clip.mp4')).toBeInTheDocument());
    expect(region()).toHaveAttribute('data-status', 'ready');
  });

  it('PromptInputSubmit icon reflects current status', async () => {
    render(<HeroDropzone />);

    expect(submitButton()).toHaveAttribute('data-status', 'ready');

    fireEvent.click(submitButton());

    await waitFor(() => expect(submitButton()).toHaveAttribute('data-status', 'error'));
  });

  it('respects prefers-reduced-motion: no entrance animation when reduced', async () => {
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: true,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));

    render(<HeroDropzone />);

    await waitFor(() => expect(region()).not.toHaveAttribute('data-animate'));
  });
});
