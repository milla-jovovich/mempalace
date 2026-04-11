import { NextRequest, NextResponse } from 'next/server';
import { getPortals, createPortal } from '@/lib/store';

export async function GET() {
  const portals = getPortals();
  return NextResponse.json(portals);
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { name, slug } = body;

    if (!name || !slug) {
      return NextResponse.json(
        { message: 'Name and slug are required' },
        { status: 400 }
      );
    }

    // Check if portal already exists
    const existing = getPortals().find(p => p.slug === slug);
    if (existing) {
      return NextResponse.json(
        { message: 'Portal with this slug already exists' },
        { status: 400 }
      );
    }

    const newPortal = createPortal(name, slug);
    
    return NextResponse.json(newPortal, { status: 201 });
  } catch (error) {
    console.error('Error creating portal:', error);
    return NextResponse.json(
      { message: 'Failed to create portal' },
      { status: 500 }
    );
  }
}
