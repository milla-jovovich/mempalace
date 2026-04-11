import { PortalConfig, PageConfig } from '@/types';

// In-memory storage for portals (in production, this would be a database)
let portals: PortalConfig[] = [];

// Initialize with default admin portal
if (portals.length === 0) {
  portals.push({
    id: 'admin',
    name: 'Admin Portal',
    slug: 'admin',
    isAdmin: true,
    pages: [
      { id: 'dashboard', name: 'Dashboard', path: '/admin/dashboard', portalId: 'admin' },
      { id: 'portals', name: 'Manage Portals', path: '/admin/portals', portalId: 'admin' },
      { id: 'pages', name: 'Manage Pages', path: '/admin/pages', portalId: 'admin' },
    ],
    createdAt: new Date().toISOString(),
  });
}

export function getPortals(): PortalConfig[] {
  return portals;
}

export function getPortalBySlug(slug: string): PortalConfig | undefined {
  return portals.find(p => p.slug === slug);
}

export function createPortal(name: string, slug: string): PortalConfig {
  const newPortal: PortalConfig = {
    id: slug.toLowerCase().replace(/\s+/g, '-'),
    name,
    slug,
    isAdmin: false,
    pages: [
      { id: 'dashboard', name: 'Dashboard', path: `/${slug}/dashboard`, portalId: slug },
    ],
    createdAt: new Date().toISOString(),
  };
  portals.push(newPortal);
  return newPortal;
}

export function addPageToPortal(portalId: string, page: Omit<PageConfig, 'id' | 'portalId'>): PageConfig {
  const portal = portals.find(p => p.id === portalId);
  if (!portal) {
    throw new Error(`Portal ${portalId} not found`);
  }
  
  const newPage: PageConfig = {
    ...page,
    id: page.name.toLowerCase().replace(/\s+/g, '-'),
    portalId,
  };
  
  portal.pages.push(newPage);
  return newPage;
}

export function getPagesForPortal(portalId: string): PageConfig[] {
  const portal = portals.find(p => p.id === portalId);
  return portal?.pages || [];
}
