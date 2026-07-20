import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

// Routes that may appear in search engines. Everything else gets an
// X-Robots-Tag: noindex header — robots.txt only stops crawling, it doesn't
// stop a URL that's linked elsewhere (e.g. a shared /q/ quote link) from being
// indexed; the header does.
const INDEXABLE_PATHS = ['/', '/hcad-data', '/login', '/signup', '/privacy', '/terms']

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl
  const isIndexable = INDEXABLE_PATHS.some(
    p => pathname === p || (p !== '/' && pathname.startsWith(p + '/')),
  )
  if (isIndexable) return NextResponse.next()

  const response = NextResponse.next()
  response.headers.set('X-Robots-Tag', 'noindex, nofollow')
  return response
}

export const config = {
  matcher: ['/((?!_next|favicon.ico|.*\\..*).*)'],
}
