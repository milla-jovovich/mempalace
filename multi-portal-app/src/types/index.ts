// Portal and page configuration types
export interface PageConfig {
  id: string;
  name: string;
  path: string;
  portalId: string;
  component?: string;
}

export interface PortalConfig {
  id: string;
  name: string;
  slug: string;
  isAdmin: boolean;
  pages: PageConfig[];
  createdAt: string;
}

export interface NavigationItem {
  name: string;
  href: string;
  children?: NavigationItem[];
}
