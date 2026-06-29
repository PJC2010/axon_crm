'use client'
import { PropertyMap } from '@/components/PropertyMap'
import { ModuleGate } from '@/components/ModuleGate'

// Service-area map route. Gated on the `map` module so accounts without it see an
// upgrade panel instead of the map.
export default function MapPage() {
  return (
    <ModuleGate module="map" feature="The property map">
      <PropertyMap />
    </ModuleGate>
  )
}
