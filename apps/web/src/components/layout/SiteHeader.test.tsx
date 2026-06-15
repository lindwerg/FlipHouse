// @vitest-environment jsdom
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { SiteHeader } from './SiteHeader';

describe('SiteHeader', () => {
  it('exposes a nav with an accessible label and a sign-in link', () => {
    render(<SiteHeader />);

    const nav = screen.getByRole('navigation', { name: /main navigation/i });

    expect(nav).toBeInTheDocument();

    const signIn = screen.getByRole('link', { name: /sign in/i });

    expect(signIn).toHaveAttribute('href', '/sign-in');
  });

  it('renders the FlipHouse wordmark as a home link', () => {
    render(<SiteHeader />);

    const wordmark = screen.getByRole('link', { name: /fliphouse/i });

    expect(wordmark).toHaveAttribute('href', '/');
  });
});
