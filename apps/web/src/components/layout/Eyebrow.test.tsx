// @vitest-environment jsdom
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Eyebrow } from './Eyebrow';

describe('Eyebrow', () => {
  it('renders a mono kicker label with its text', () => {
    render(<Eyebrow>From the cut</Eyebrow>);

    const label = screen.getByText('From the cut');

    expect(label).toBeInTheDocument();
    expect(label).toHaveAttribute('data-slot', 'eyebrow');
  });
});
