// Numbered Swiss section header (docs/design-reference/swiss-pop.html): a mono
// section number in --pop, a grotesk title carrying the id that the section's
// aria-labelledby points at, and a narrow right-aligned aside.

export type SectionHeadProps = {
  num: string;
  id: string;
  title: string;
  aside: string;
};

export function SectionHead({ num, id, title, aside }: SectionHeadProps) {
  return (
    <div data-reveal="rise" className="mb-8 grid grid-cols-12 items-end gap-[var(--space-gutter)] border-b-[1.5px] border-[var(--rule-strong)] pb-4 md:mb-12">
      <span className="col-span-12 font-mono text-lg font-semibold tracking-wide text-[var(--pop)] md:col-span-2 md:text-2xl">
        {num}
      </span>
      <h2
        id={id}
        className="col-span-12 mt-2 font-[family-name:var(--font-grotesk)] font-extrabold leading-[0.98] tracking-tight md:col-span-7 md:mt-0"
        style={{ fontSize: 'var(--text-sec)' }}
      >
        {title}
      </h2>
      <p className="col-span-12 mt-3 font-[family-name:var(--font-narrow)] font-semibold leading-snug text-[var(--ink-soft)] md:col-start-10 md:col-span-3 md:mt-0 md:text-right">
        {aside}
      </p>
    </div>
  );
}
