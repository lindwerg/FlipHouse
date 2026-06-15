// @vitest-environment jsdom
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { AnimatedHeading } from '@/components/ui/AnimatedHeading';
import { Landing } from './Landing';

describe('Landing', () => {
  it('landing renders a single h1 inside hero section', () => {
    const { container } = render(<Landing />);

    const h1s = container.querySelectorAll('h1');

    expect(h1s).toHaveLength(1);

    const heroSection = h1s[0]!.closest('section');

    expect(heroSection).toHaveAttribute('aria-labelledby', 'hero-h');
    expect(h1s[0]).toHaveAttribute('id', 'hero-h');
  });

  it('landing exposes semantic landmarks header/main/footer', () => {
    render(<Landing />);

    expect(screen.getByRole('banner')).toBeInTheDocument();
    expect(screen.getByRole('main')).toBeInTheDocument();
    expect(screen.getByRole('contentinfo')).toBeInTheDocument();
  });

  it('navbar has aria-label Main navigation and links to sign-in', () => {
    render(<Landing />);

    const nav = screen.getByRole('navigation', { name: /основная навигация/i });

    expect(nav).toBeInTheDocument();

    const signIn = screen.getByRole('link', { name: /войти/i });

    expect(signIn).toHaveAttribute('href', '/sign-in');
  });

  it('each section has an aria-labelledby pointing to a real heading id', () => {
    const { container } = render(<Landing />);

    const sections = container.querySelectorAll('section[aria-labelledby]');

    expect(sections.length).toBeGreaterThanOrEqual(5);

    for (const section of sections) {
      const id = section.getAttribute('aria-labelledby');

      expect(id).toBeTruthy();

      const heading = container.querySelector(`#${id}`);

      expect(heading).toBeInTheDocument();
      expect(heading!.tagName).toMatch(/^H[1-6]$/);
    }
  });

  it('AnimatedHeading splits text into word spans for reveal', () => {
    const { container } = render(<AnimatedHeading text="одно видео шортсы" />);

    const words = container.querySelectorAll('[data-slot="word"]');

    expect(words).toHaveLength(3);
    expect(Array.from(words).map(w => w.textContent)).toEqual([
      'одно',
      'видео',
      'шортсы',
    ]);
  });
});
