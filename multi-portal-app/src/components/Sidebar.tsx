'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { NavigationItem } from '@/types';

interface SidebarProps {
  navigation: NavigationItem[];
  portalName: string;
  portalSlug: string;
}

export default function Sidebar({ navigation, portalName, portalSlug }: SidebarProps) {
  const pathname = usePathname();

  return (
    <div className="flex h-screen flex-col bg-gray-900 text-white w-64">
      {/* Portal Header */}
      <div className="flex items-center justify-between p-4 border-b border-gray-700">
        <Link href={`/${portalSlug}`} className="text-xl font-bold">
          {portalName}
        </Link>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto p-4">
        <ul className="space-y-2">
          {navigation.map((item) => (
            <li key={item.name}>
              {item.children ? (
                <div className="space-y-1">
                  <span className="block px-3 py-2 text-sm font-medium text-gray-400 uppercase tracking-wider">
                    {item.name}
                  </span>
                  <ul className="ml-4 space-y-1">
                    {item.children.map((child) => (
                      <li key={child.name}>
                        <Link
                          href={child.href}
                          className={`block px-3 py-2 rounded-md text-sm transition-colors ${
                            pathname === child.href
                              ? 'bg-blue-600 text-white'
                              : 'text-gray-300 hover:bg-gray-800 hover:text-white'
                          }`}
                        >
                          {child.name}
                        </Link>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : (
                <Link
                  href={item.href}
                  className={`block px-3 py-2 rounded-md text-sm transition-colors ${
                    pathname === item.href
                      ? 'bg-blue-600 text-white'
                      : 'text-gray-300 hover:bg-gray-800 hover:text-white'
                  }`}
                >
                  {item.name}
                </Link>
              )}
            </li>
          ))}
        </ul>
      </nav>

      {/* Footer */}
      <div className="p-4 border-t border-gray-700">
        <Link
          href="/admin"
          className="block px-3 py-2 text-sm text-gray-400 hover:text-white transition-colors"
        >
          ← Back to Admin
        </Link>
      </div>
    </div>
  );
}
