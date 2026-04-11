import Link from 'next/link';

export default function Home() {
  return (
    <div className="min-h-screen bg-gradient-to-b from-gray-50 to-gray-100">
      <main className="max-w-7xl mx-auto px-4 py-16">
        <div className="text-center">
          <h1 className="text-5xl font-bold text-gray-900 mb-4">
            Multi-Portal Application
          </h1>
          <p className="text-xl text-gray-600 mb-8">
            Manage multiple portals with dynamic page creation and navigation
          </p>
          
          <div className="flex justify-center gap-4">
            <Link
              href="/admin"
              className="px-8 py-3 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 transition-colors shadow-lg"
            >
              Go to Admin Portal
            </Link>
          </div>

          <div className="mt-16 grid grid-cols-1 md:grid-cols-3 gap-8 text-left">
            <div className="bg-white p-6 rounded-lg shadow-md">
              <h3 className="text-lg font-semibold text-gray-900 mb-2">
                🏢 Multiple Portals
              </h3>
              <p className="text-gray-600">
                Create and manage multiple portals, each with their own admin area and pages.
              </p>
            </div>
            
            <div className="bg-white p-6 rounded-lg shadow-md">
              <h3 className="text-lg font-semibold text-gray-900 mb-2">
                📄 Dynamic Pages
              </h3>
              <p className="text-gray-600">
                Create pages at runtime that automatically appear in the navigation sidebar.
              </p>
            </div>
            
            <div className="bg-white p-6 rounded-lg shadow-md">
              <h3 className="text-lg font-semibold text-gray-900 mb-2">
                🗂️ Folder-based Navigation
              </h3>
              <p className="text-gray-600">
                Organize pages into folders to create submenus in the navigation.
              </p>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
