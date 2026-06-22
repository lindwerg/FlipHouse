// @vitest-environment jsdom
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { ClipView } from './api-schemas';
import { RankedBatchView } from './RankedBatchView';

function clip(overrides: Partial<ClipView> = {}): ClipView {
  return {
    rank: 0,
    score: 87.5,
    startTime: 12,
    endTime: 41.5,
    durationS: 29.5,
    width: 1080,
    height: 1920,
    clipUrl: 'https://clips.example.com/clips/a/clip_00.mp4',
    title: 'Лучший момент',
    ...overrides,
  };
}

describe('RankedBatchView', () => {
  it('shows an empty-state message when there are no clips', () => {
    render(<RankedBatchView clips={[]} />);
    expect(screen.getByText(/готовых клипов пока нет/i)).toBeInTheDocument();
  });

  it('renders one ranked list item per clip with its title and mmss range', () => {
    render(
      <RankedBatchView
        clips={[clip(), clip({ rank: 1, title: 'Второй', startTime: 754, endTime: 770 })]}
      />,
    );

    const items = screen.getAllByRole('listitem');
    expect(items).toHaveLength(2);
    expect(screen.getByText('Лучший момент')).toBeInTheDocument();
    expect(screen.getByText('Второй')).toBeInTheDocument();
    expect(screen.getByText(/0:12 — 0:41/)).toBeInTheDocument();
    expect(screen.getByText(/12:34 — 12:50/)).toBeInTheDocument();
  });

  it('renders a 9:16 video with explicit dimensions and metadata preload', () => {
    const { container } = render(<RankedBatchView clips={[clip()]} />);
    const video = container.querySelector('video');

    expect(video).not.toBeNull();
    expect(video?.getAttribute('width')).toBe('1080');
    expect(video?.getAttribute('height')).toBe('1920');
    expect(video?.getAttribute('preload')).toBe('metadata');
    expect(container.querySelector('source')?.getAttribute('src')).toBe(
      'https://clips.example.com/clips/a/clip_00.mp4',
    );
  });

  it('exposes a download link to each clip URL', () => {
    render(<RankedBatchView clips={[clip()]} />);
    const link = screen.getByRole('link', { name: /скачать/i });

    expect(link).toHaveAttribute('href', 'https://clips.example.com/clips/a/clip_00.mp4');
    expect(link).toHaveAttribute('download');
  });

  it('defers below-fold videos (rank >= 2) via preload=none, keeping the top ones at metadata', () => {
    const { container } = render(
      <RankedBatchView
        clips={[clip(), clip({ rank: 1 }), clip({ rank: 2 })]}
      />,
    );
    const videos = container.querySelectorAll('video');

    expect(videos[0]?.getAttribute('preload')).toBe('metadata');
    expect(videos[1]?.getAttribute('preload')).toBe('metadata');
    expect(videos[2]?.getAttribute('preload')).toBe('none');
  });
});
