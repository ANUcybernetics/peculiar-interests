/** Every internal href goes through here so a base-path change is one edit. */
export function withBase(path: string): string {
  const base = import.meta.env.BASE_URL.replace(/\/$/, "");
  return `${base}${path.startsWith("/") ? path : `/${path}`}`;
}

export function personPath(aphId: string): string {
  return withBase(`/people/${aphId}`);
}

export function categoryPath(category: string): string {
  return withBase(`/items/${category}`);
}

export function mentionPath(slug: string): string {
  return withBase(`/mentions/${slug}`);
}

/** URL-safe key for a declared string (company, creditor, sponsor …). Pure,
 * so the same name always lands on the same page. */
export function slugify(text: string): string {
  return text
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/&/g, " and ")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80);
}
