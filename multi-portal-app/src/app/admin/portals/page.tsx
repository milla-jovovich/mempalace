'use client';

import { useState, useEffect } from 'react';
import CreatePortalForm from '@/components/CreatePortalForm';
import { PortalConfig } from '@/types';

export default function ManagePortals() {
  const [portals, setPortals] = useState<PortalConfig[]>([]);
  const [showCreateForm, setShowCreateForm] = useState(false);

  useEffect(() => {
    fetchPortals();
  }, []);

  const fetchPortals = async () => {
    try {
      const response = await fetch('/api/portals');
      if (response.ok) {
        const data = await response.json();
        setPortals(data);
      }
    } catch (error) {
      console.error('Error fetching portals:', error);
    }
  };

  const handlePortalCreated = () => {
    setShowCreateForm(false);
    fetchPortals();
  };

  return (
    <div className="min-h-screen bg-gray-100">
      <header className="bg-white shadow">
        <div className="max-w-7xl mx-auto px-4 py-6 sm:px-6 lg:px-8">
          <h1 className="text-3xl font-bold text-gray-900">Manage Portals</h1>
          <p className="mt-2 text-gray-600">Create and configure new portals</p>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 py-8 sm:px-6 lg:px-8">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          {/* Create Portal Form */}
          <div className="bg-white rounded-lg shadow p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xl font-semibold text-gray-900">Create New Portal</h2>
            </div>
            <CreatePortalForm onPortalCreated={handlePortalCreated} />
          </div>

          {/* Portal List */}
          <div className="bg-white rounded-lg shadow p-6">
            <h2 className="text-xl font-semibold text-gray-900 mb-4">Existing Portals</h2>
            <div className="space-y-4">
              {portals.map((portal) => (
                <div
                  key={portal.id}
                  className="border border-gray-200 rounded-lg p-4"
                >
                  <div className="flex items-center justify-between">
                    <div>
                      <h3 className="font-semibold text-gray-900">{portal.name}</h3>
                      <p className="text-sm text-gray-500">/{portal.slug}</p>
                    </div>
                    <div className="flex items-center gap-2">
                      {portal.isAdmin && (
                        <span className="px-2 py-1 text-xs bg-blue-100 text-blue-800 rounded">
                          Admin
                        </span>
                      )}
                      <a
                        href={`/${portal.slug}`}
                        className="text-blue-600 hover:text-blue-800 text-sm font-medium"
                      >
                        Open →
                      </a>
                    </div>
                  </div>
                  <div className="mt-2 text-sm text-gray-600">
                    {portal.pages.length} pages • Created {new Date(portal.createdAt).toLocaleDateString()}
                  </div>
                </div>
              ))}
              {portals.length === 0 && (
                <p className="text-gray-500 text-center py-4">No portals yet. Create your first portal!</p>
              )}
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
