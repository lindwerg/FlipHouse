// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Dropzone, DropzoneEmptyState } from './dropzone';
import {
  PromptInput,
  PromptInputSubmit,
  PromptInputTextarea,
  PromptInputToolbar,
} from './prompt-input';

describe('PromptInput', () => {
  it('renders a textarea and submit button', () => {
    render(
      <PromptInput>
        <PromptInputTextarea placeholder="Вставьте ссылку на видео" />
        <PromptInputToolbar>
          <PromptInputSubmit />
        </PromptInputToolbar>
      </PromptInput>,
    );

    expect(screen.getByRole('textbox')).toBeInTheDocument();
    expect(screen.getByRole('button')).toBeInTheDocument();
  });
});

describe('Dropzone', () => {
  it('renders empty state copy with max files and size', () => {
    render(
      <Dropzone accept={{ 'video/*': [] }} maxFiles={1} maxSize={4 * 1024 * 1024 * 1024}>
        <DropzoneEmptyState />
      </Dropzone>,
    );

    expect(screen.getByText(/1 файл/)).toBeInTheDocument();
    expect(screen.getByText(/4\s*ГБ/)).toBeInTheDocument();
  });

  it('applies drag-active styles when isDragActive', async () => {
    render(
      <Dropzone accept={{ 'video/*': [] }} maxFiles={1}>
        <DropzoneEmptyState />
      </Dropzone>,
    );

    const root = screen.getByRole('button');

    expect(root).not.toHaveAttribute('data-drag-active');

    const file = new File(['x'], 'v.mp4', { type: 'video/mp4' });
    fireEvent.dragEnter(root, {
      dataTransfer: {
        types: ['Files'],
        files: [file],
        items: [{ kind: 'file', type: 'video/mp4', getAsFile: () => file }],
      },
    });

    // react-dropzone resolves files asynchronously before flipping isDragActive.
    await waitFor(() => expect(root).toHaveAttribute('data-drag-active', 'true'));
  });
});
