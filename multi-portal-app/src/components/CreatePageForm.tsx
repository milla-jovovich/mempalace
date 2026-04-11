'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';

interface CreatePageFormProps {
  portalId: string;
  onPageCreated: () => void;
}

export default function CreatePageForm({ portalId, onPageCreated }: CreatePageFormProps) {
  const [name, setName] = useState('');
  const [folder, setFolder] = useState('');
  const router = useRouter();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!name) {
      alert('Please enter a page name');
      return;
    }

    try {
      const response = await fetch('/api/pages', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          portalId, 
          name,
          folder: folder || 'general'
        }),
      });

      if (response.ok) {
        const data = await response.json();
        onPageCreated();
        // Navigate to the new page
        router.push(data.path);
      } else {
        const error = await response.json();
        alert(error.message || 'Failed to create page');
      }
    } catch (error) {
      console.error('Error creating page:', error);
      alert('Failed to create page');
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label htmlFor="name" className="block text-sm font-medium text-gray-700">
          Page Name
        </label>
        <input
          type="text"
          id="name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          placeholder="Enter page name"
        />
      </div>

      <div>
        <label htmlFor="folder" className="block text-sm font-medium text-gray-700">
          Folder (creates submenu)
        </label>
        <input
          type="text"
          id="folder"
          value={folder}
          onChange={(e) => setFolder(e.target.value)}
          className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          placeholder="Leave empty for general folder"
        />
        <p className="mt-1 text-sm text-gray-500">
          Enter a folder name to create a submenu in navigation
        </p>
      </div>

      <button
        type="submit"
        className="w-full flex justify-center py-2 px-4 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-green-600 hover:bg-green-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-green-500"
      >
        Create Page
      </button>
    </form>
  );
}
