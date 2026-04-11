import { NextRequest, NextResponse } from 'next/server';
import { getPortalBySlug, addPageToPortal, getPagesForPortal } from '@/lib/store';

export async function GET(request: NextRequest) {
  const searchParams = request.nextUrl.searchParams;
  const portalId = searchParams.get('portalId');

  if (!portalId) {
    return NextResponse.json(
      { message: 'Portal ID is required' },
      { status: 400 }
    );
  }

  const pages = getPagesForPortal(portalId);
  return NextResponse.json(pages);
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { portalId, name, folder = 'general' } = body;

    if (!portalId || !name) {
      return NextResponse.json(
        { message: 'Portal ID and page name are required' },
        { status: 400 }
      );
    }

    // Check if portal exists
    const portal = getPortalBySlug(portalId);
    if (!portal) {
      return NextResponse.json(
        { message: 'Portal not found' },
        { status: 404 }
      );
    }

    // Create the page
    const newPage = addPageToPortal(portalId, {
      name,
      path: `/${portalId}/${folder}/${name.toLowerCase().replace(/\s+/g, '-')}`,
    });

    return NextResponse.json(newPage, { status: 201 });
  } catch (error) {
    console.error('Error creating page:', error);
    return NextResponse.json(
      { message: 'Failed to create page' },
      { status: 500 }
    );
  }
}
