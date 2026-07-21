/**
 * Landing-page social proof. Copy drops in here without a code change; the
 * proof band in LandingContent renders nothing while this list is empty.
 *
 * Rules (see the UX audit): real customers only — never fabricate. Each entry
 * should carry a concrete number ("booked 4 jobs off my first ZIP pull"), the
 * person's first name + last initial, trade, and city, all with their consent.
 */
/**
 * Master switch for the landing proof band. Off for now — the section is fully
 * built (component markup + landing.css `.lp-proof-band`) and stays in the tree;
 * flip this to `true` once real quotes are added below to bring it back with no
 * other code change. Even when true, the band hides while TESTIMONIALS is empty.
 */
export const SHOW_TESTIMONIALS = false

export interface Testimonial {
  /** e.g. "Mike R." */
  name: string
  /** e.g. "Roofing" */
  trade: string
  /** e.g. "Katy, TX" */
  city: string
  /** One or two short sentences, ideally with a concrete number. */
  quote: string
}

export const TESTIMONIALS: Testimonial[] = [
  // Intentionally empty until real customer quotes exist. Example shape:
  // { name: 'Mike R.', trade: 'Roofing', city: 'Katy, TX',
  //   quote: 'Booked 4 jobs off my first ZIP pull.' },
]
