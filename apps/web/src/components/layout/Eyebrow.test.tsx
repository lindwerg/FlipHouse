// @vitest-environment jsdom
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Eyebrow } from './Eyebrow';

describe('Eyebrow', () => {
  it('renders a mono kicker label with its text', () => {
    render(<Eyebrow>Из нарезки</Eyebrow>);

    const label = screen.getByText('Из нарезки');

    expect(label).toBeInTheDocument();
    expect(label).toHaveAttribute('data-slot', 'eyebrow');
  });
});
