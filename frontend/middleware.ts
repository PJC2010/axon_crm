import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

const PUBLIC_PATHS = ['/login']

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl
  const isPublic = PUBLIC_PATHS.some(p => pathname.startsWith(p))
  if (isPublic) return NextResponse.next()

  // Token is in localStorage (client-side only) — we can't read it in middleware.
  // Instead we rely on the API client's 401 → redirect to /login pattern.
  // This middleware only handles the root redirect.
  if (pathname === '/') {
    return NextResponse.redirect(new URL('/home', request.url))
  }

  return NextResponse.next()
}

export const config = {
  matcher: ['/((?!_next|favicon.ico|.*\\..*).*)'],
}
