/**
 * URL router — A1 perfect-flow shell (§3, §6.2).
 *
 * Pure module: no imports, no DOM, no network. It is the single source
 * of truth for the 8 destinations, their URL shapes, and the redirects
 * from the old destination ids. The shell (tabs.js) consumes it; the
 * tests import it directly from Node.
 *
 * Destinations, in sidebar order:
 *   Chat, Projects, Studio, Code, Research, Agents, Library, Settings.
 * Chat is pinned and is the only chat surface; it is never closed,
 * duplicated, or nested inside another destination.
 */

// Sidebar order is part of the spec — do not reorder without a spec change.
export const DESTINATIONS = [
  { id: 'chat', title: 'Chat', icon: 'fa-message', path: '/chat' },
  { id: 'projects', title: 'Projects', icon: 'fa-folder-open', path: '/projects' },
  { id: 'studio', title: 'Studio', icon: 'fa-wand-magic-sparkles', path: '/studio' },
  { id: 'code', title: 'Code', icon: 'fa-code', path: '/code' },
  { id: 'research', title: 'Research', icon: 'fa-magnifying-glass', path: '/research' },
  { id: 'agents', title: 'Agents', icon: 'fa-robot', path: '/agents' },
  { id: 'library', title: 'Library', icon: 'fa-book', path: '/library' },
  { id: 'settings', title: 'Settings', icon: 'fa-gear', path: '/settings' },
];

export const DESTINATION_IDS = DESTINATIONS.map((d) => d.id);

export function destinationById(id) {
  return DESTINATIONS.find((d) => d.id === id) || null;
}

/** Old in-app destination ids -> their new URL. Never a 404. */
export const LEGACY_ID_REDIRECTS = {
  home: '/chat',
  work: '/agents',
  create: '/studio',
  knowledge: '/research',
  agents: '/agents',
  teams: '/agents?section=hub',
  compare: '/agents?section=hub',
  code: '/code',
  workflows: '/agents?section=workflows',
  runs: '/agents?section=run-history',
  activity: '/agents?section=run-history',
  media: '/studio?section=media',
  images: '/studio?section=create',
  voice: '/studio?section=create',
  design: '/studio?section=design',
  skills: '/library?section=skills',
  learn: '/research?section=explore',
  analytics: '/settings/data',
};

/** Old URL paths (if a bookmark or link still uses them) -> new URL. */
export const LEGACY_PATH_REDIRECTS = {
  '/home': '/chat',
  '/work': '/agents',
  '/create': '/studio',
  '/knowledge': '/research',
};

/** Detail-param names per destination, for breadcrumbs. */
const PARAM_LABEL = {
  projects: 'Project',
  studio: 'Artifact',
  code: 'Repo',
  research: 'Notebook',
  agents: 'Task',
};

/**
 * Parse a URL (pathname + optional query string, e.g. "/agents?section=tasks").
 * Returns one of:
 *   { dest, param, section, depth, breadcrumb, path } — depth is 1 for a
 *     destination landing page, 2 for a detail page or a settings section.
 *   { redirect: '/chat' } — for '/' and legacy paths.
 *   { notFound: true, path } — unknown routes render the 404 page.
 * Section (the ?section= segment inside a destination) does not raise
 * depth: it is sub-navigation inside the destination, not a new page.
 */
export function parseRoute(url) {
  const [rawPath, rawQuery] = String(url || '').split('?');
  let path = rawPath || '/';
  if (path.length > 1 && path.endsWith('/')) path = path.slice(0, -1);
  if (path === '/' || path === '') return { redirect: '/chat', path: '/chat' };
  if (LEGACY_PATH_REDIRECTS[path]) {
    return { redirect: LEGACY_PATH_REDIRECTS[path], path: LEGACY_PATH_REDIRECTS[path] };
  }
  const params = new URLSearchParams(rawQuery || '');
  const section = params.get('section') || null;
  const parts = path.split('/').filter(Boolean);
  const dest = destinationById(parts[0]);
  if (!dest) return { notFound: true, path };
  if (parts.length === 1) {
    const breadcrumb = [dest.title];
    if (dest.id === 'settings' && section) breadcrumb.push(section);
    return {
      dest: dest.id, param: null, section,
      depth: dest.id === 'settings' && section ? 2 : 1,
      breadcrumb, path,
    };
  }
  if (parts.length === 2) {
    // Settings is special: /settings/:section is a section, not a
    // detail param (Settings has no detail pages).
    if (dest.id === 'settings') {
      const sectionName = decodeURIComponent(parts[1]);
      return {
        dest: 'settings', param: null, section: sectionName,
        depth: 2,
        breadcrumb: ['Settings', sectionName],
        path,
      };
    }
    const param = decodeURIComponent(parts[1]);
    const label = PARAM_LABEL[dest.id];
    if (!label) return { notFound: true, path };
    return {
      dest: dest.id, param, section,
      depth: 2,
      breadcrumb: [dest.title, param],
      path,
    };
  }
  return { notFound: true, path };
}

/** Build a URL for a destination, optional detail param, optional section. */
export function urlFor(dest, { param = null, section = null } = {}) {
  const base = destinationById(dest);
  if (!base) return '/chat';
  // Settings sections live in the path (/settings/:section), not the query.
  if (dest === 'settings' && section) return `/settings/${encodeURIComponent(section)}`;
  let url = base.path;
  if (param) url += `/${encodeURIComponent(String(param))}`;
  if (section) url += `?section=${encodeURIComponent(section)}`;
  return url;
}

/** Resolve an old destination id (or a current one) to a URL, or null. */
export function resolveLegacyId(id) {
  if (destinationById(id)) return destinationById(id).path;
  return LEGACY_ID_REDIRECTS[id] || null;
}

/** Breadcrumb text: shown only when depth > 1, else null. */
export function breadcrumbText(parsed) {
  if (!parsed || parsed.notFound || parsed.redirect) return null;
  if ((parsed.depth || 1) <= 1) return null;
  return parsed.breadcrumb.join(' / ');
}
