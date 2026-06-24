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

  it('rejects file over maxSize 4GB and sets status error', async () => {
    render(<HeroDropzone />);

    dropFileOn(dropBox(), makeVideoFile('big.mp4', 5 * 1024 * 1024 * 1024));

    await waitFor(() => expect(region()).toHaveAttribute('data-status', 'error'));
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  it('submit with no file sets status error and does not call onFlip', async () => {
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

  it('hero dropzone is a single bordered dropbar container', () => {
    const { container } = render(<HeroDropzone />);

    const dropbars = container.querySelectorAll('[data-slot="dropbar"]');

    expect(dropbars).toHaveLength(1);

    const dropbar = dropbars[0] as HTMLElement;

    expect(dropbar).toHaveClass('border-[var(--rule-strong)]');
    expect(dropbar).toContainElement(
      container.querySelector('[data-slot="dropzone"]') as HTMLElement,
    );
    expect(dropbar).toContainElement(submitButton());
  });

  it('controlled uploadStatus="hashing" maps to submitted and shows the hashing label', () => {
    render(<HeroDropzone uploadStatus="hashing" />);

    expect(region()).toHaveAttribute('data-status', 'submitted');
    expect(submitButton()).toHaveAttribute('data-status', 'submitted');
    expect(screen.getByText(/считаем отпечаток/i)).toBeInTheDocument();
  });

  it('controlled uploadStatus="uploading" shows a progressbar reflecting progress', () => {
    const { container } = render(<HeroDropzone uploadStatus="uploading" progress={40} />);

    expect(region()).toHaveAttribute('data-status', 'streaming');
    const bar = screen.getByRole('progressbar', { name: /прогресс загрузки/i });

    expect(bar).toHaveAttribute('aria-valuenow', '40');
    expect(container.querySelector('[data-slot="upload-progress-fill"]')).toHaveStyle({
      transform: 'scaleX(0.4)',
    });
  });

  it('controlled uploading with no progress prop defaults the bar to 0', () => {
    render(<HeroDropzone uploadStatus="uploading" />);

    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '0');
  });

  it('controlled uploadStatus="done" maps to streaming and shows the done label', () => {
    render(<HeroDropzone uploadStatus="done" />);

    expect(region()).toHaveAttribute('data-status', 'streaming');
    expect(screen.getByText(/готово/i)).toBeInTheDocument();
  });

  it('controlled uploadStatus="idle" maps to ready with no progress block', () => {
    const { container } = render(<HeroDropzone uploadStatus="idle" />);

    expect(region()).toHaveAttribute('data-status', 'ready');
    expect(container.querySelector('[data-slot="upload-progress"]')).toBeNull();
  });

  it('controlled uploadStatus="error" with uploadError surfaces it as a role=alert', () => {
    render(<HeroDropzone uploadStatus="error" uploadError="Не удалось загрузить видео" />);

    expect(region()).toHaveAttribute('data-status', 'error');
    expect(screen.getByRole('alert')).toHaveTextContent('Не удалось загрузить видео');
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
