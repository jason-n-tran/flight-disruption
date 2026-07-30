// Fully static SPA: prerender the shell, disable SSR (Cloudflare Pages free tier).
export const prerender = true;
export const ssr = false;
export const trailingSlash = 'ignore';
