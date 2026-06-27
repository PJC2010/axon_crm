import { PropertyMap } from '@/components/PropertyMap'

// Service-area map route. (Redeploy trigger: refresh production build so the
// cached dashboard bundle picks up the Map nav link.)
export default function MapPage() {
  return <PropertyMap />
}
