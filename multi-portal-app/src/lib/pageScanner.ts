import fs from 'fs';
import path from 'path';
import { NavigationItem } from '@/types';

// This function scans the pages folder and builds navigation structure
export function scanPagesFolder(basePath: string): NavigationItem[] {
  const navigation: NavigationItem[] = [];
  
  try {
    const pagesDir = path.join(process.cwd(), basePath);
    
    if (!fs.existsSync(pagesDir)) {
      return navigation;
    }
    
    const entries = fs.readdirSync(pagesDir, { withFileTypes: true });
    
    entries.forEach(entry => {
      // Skip non-directory entries and special folders
      if (!entry.isDirectory() || entry.name.startsWith('_')) {
        return;
      }
      
      const folderPath = path.join(pagesDir, entry.name);
      const folderFiles = fs.readdirSync(folderPath, { withFileTypes: true });
      
      // Filter for page files (only .tsx or .ts files that are pages)
      const pageFiles = folderFiles.filter(file => 
        file.isFile() && 
        (file.name.endsWith('.tsx') || file.name.endsWith('.ts')) &&
        file.name !== 'index.ts' &&
        file.name !== 'index.tsx'
      );
      
      if (pageFiles.length > 0 || hasSubFolders(folderPath)) {
        const navItem: NavigationItem = {
          name: capitalizeFirst(entry.name),
          href: `/${entry.name}`,
          children: [],
        };
        
        // Add individual pages in this folder
        pageFiles.forEach(file => {
          const fileName = file.name.replace(/\.(tsx|ts)$/, '');
          if (fileName !== 'page' && fileName !== 'layout') {
            navItem.children?.push({
              name: capitalizeFirst(fileName),
              href: `/${entry.name}/${fileName}`,
            });
          }
        });
        
        // Check for subfolders and create submenus
        const subFolders = folderFiles.filter(f => f.isDirectory() && !f.name.startsWith('_'));
        if (subFolders.length > 0) {
          subFolders.forEach(subFolder => {
            navItem.children?.push({
              name: capitalizeFirst(subFolder.name),
              href: `/${entry.name}/${subFolder.name}`,
            });
          });
        }
        
        // If no children, remove the children property
        if (navItem.children?.length === 0) {
          delete navItem.children;
        }
        
        navigation.push(navItem);
      }
    });
  } catch (error) {
    console.error('Error scanning pages folder:', error);
  }
  
  return navigation;
}

function hasSubFolders(folderPath: string): boolean {
  try {
    const entries = fs.readdirSync(folderPath, { withFileTypes: true });
    return entries.some(entry => entry.isDirectory() && !entry.name.startsWith('_'));
  } catch {
    return false;
  }
}

function capitalizeFirst(str: string): string {
  return str.charAt(0).toUpperCase() + str.slice(1);
}

// Build navigation items from portal pages
export function buildPortalNavigation(portalSlug: string, pages: Array<{ name: string; path: string }>): NavigationItem[] {
  const navItems: NavigationItem[] = [];
  const folderMap = new Map<string, NavigationItem>();
  
  pages.forEach(page => {
    // Extract folder from path (e.g., /admin/dashboard -> admin)
    const parts = page.path.split('/').filter(Boolean);
    
    if (parts.length >= 2) {
      const folderName = parts[0];
      const pageName = parts[parts.length - 1];
      
      if (!folderMap.has(folderName)) {
        folderMap.set(folderName, {
          name: capitalizeFirst(folderName),
          href: `/${folderName}`,
          children: [],
        });
      }
      
      const folder = folderMap.get(folderName)!;
      folder.children?.push({
        name: capitalizeFirst(pageName),
        href: page.path,
      });
    } else if (parts.length === 1) {
      navItems.push({
        name: capitalizeFirst(parts[0]),
        href: page.path,
      });
    }
  });
  
  // Add grouped folders
  folderMap.forEach(folder => {
    if (folder.children?.length === 1) {
      // If only one child, flatten it
      navItems.push({
        name: folder.children[0].name,
        href: folder.children[0].href,
      });
    } else {
      navItems.push(folder);
    }
  });
  
  return navItems;
}
