import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

const PUBLIC_PATHS = ['/', '/login']

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl
  const isPublic = PUBLIC_PATHS.some(p => pathname === p || pathname.startsWith(p + '/'))
  if (isPublic) return NextResponse.next()

  return NextResponse.next()
}

export const config = {
  matcher: ['/((?!_next|favicon.ico|.*\\..*).*)'],
}
