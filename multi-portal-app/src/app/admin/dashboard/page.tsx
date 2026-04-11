import Link from 'next/link';
import { getPortals } from '@/lib/store';
import { buildPortalNavigation } from '@/lib/pageScanner';

export default function AdminDashboard() {
  const portals = getPortals();
  
  // Build navigation for admin portal
  const adminPortal = portals.find(p => p.isAdmin);
  const navigation = adminPortal 
    ? buildPortalNavigation('admin', adminPortal.pages.map(p => ({ name: p.name, path: p.path })))
    : [];

  return (
    <div className="min-h-screen bg-gray-100">
      {/* Header */}
      <header className="bg-white shadow">
        <div className="max-w-7xl mx-auto px-4 py-6 sm:px-6 lg:px-8">
          <h1 className="text-3xl font-bold text-gray-900">Admin Portal</h1>
          <p className="mt-2 text-gray-600">Manage all portals and pages from here</p>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 py-8 sm:px-6 lg:px-8">
        {/* Quick Actions */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
          <Link
            href="/admin/portals"
            className="bg-white p-6 rounded-lg shadow-md hover:shadow-lg transition-shadow"
          >
            <h3 className="text-lg font-semibold text-gray-900 mb-2">🏢 Manage Portals</h3>
            <p className="text-gray-600">Create and configure new portals</p>
          </Link>

          <Link
            href="/admin/pages"
            className="bg-white p-6 rounded-lg shadow-md hover:shadow-lg transition-shadow"
          >
            <h3 className="text-lg font-semibold text-gray-900 mb-2">📄 Manage Pages</h3>
            <p className="text-gray-600">Create and organize pages</p>
          </Link>

          <Link
            href="/admin/dashboard"
            className="bg-white p-6 rounded-lg shadow-md hover:shadow-lg transition-shadow"
          >
            <h3 className="text-lg font-semibold text-gray-900 mb-2">📊 Dashboard</h3>
            <p className="text-gray-600">View system overview</p>
          </Link>
        </div>

        {/* All Portals */}
        <div className="bg-white rounded-lg shadow">
          <div className="px-6 py-4 border-b border-gray-200">
            <h2 className="text-xl font-semibold text-gray-900">All Portals</h2>
          </div>
          <div className="p-6">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {portals.map((portal) => (
                <div
                  key={portal.id}
                  className="border border-gray-200 rounded-lg p-4 hover:border-blue-500 transition-colors"
                >
                  <div className="flex items-center justify-between mb-2">
                    <h3 className="font-semibold text-gray-900">{portal.name}</h3>
                    {portal.isAdmin && (
                      <span className="px-2 py-1 text-xs bg-blue-100 text-blue-800 rounded">
                        Admin
                      </span>
                    )}
                  </div>
                  <p className="text-sm text-gray-500 mb-3">/{portal.slug}</p>
                  <p className="text-sm text-gray-600 mb-4">
                    {portal.pages.length} pages
                  </p>
                  <Link
                    href={`/${portal.slug}`}
                    className="text-blue-600 hover:text-blue-800 text-sm font-medium"
                  >
                    Open Portal →
                  </Link>
                </div>
              ))}
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
