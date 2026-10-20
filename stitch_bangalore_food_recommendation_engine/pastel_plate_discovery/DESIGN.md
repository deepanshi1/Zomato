---
name: Pastel Plate Discovery
colors:
  surface: '#fff7fa'
  surface-dim: '#e8d5e3'
  surface-bright: '#fff7fa'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#ffeffa'
  surface-container: '#fce8f7'
  surface-container-high: '#f6e3f1'
  surface-container-highest: '#f0ddec'
  on-surface: '#231822'
  on-surface-variant: '#534346'
  inverse-surface: '#392d38'
  inverse-on-surface: '#ffebfa'
  outline: '#857276'
  outline-variant: '#d8c1c5'
  surface-tint: '#93455f'
  primary: '#93455f'
  on-primary: '#ffffff'
  primary-container: '#ff9ebb'
  on-primary-container: '#7b314b'
  inverse-primary: '#ffb1c7'
  secondary: '#765841'
  on-secondary: '#ffffff'
  secondary-container: '#fed5b7'
  on-secondary-container: '#795b43'
  tertiary: '#2e694c'
  on-tertiary: '#ffffff'
  tertiary-container: '#8bc8a5'
  on-tertiary-container: '#175539'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#ffd9e2'
  primary-fixed-dim: '#ffb1c7'
  on-primary-fixed: '#3e011c'
  on-primary-fixed-variant: '#762d47'
  secondary-fixed: '#ffdcc3'
  secondary-fixed-dim: '#e6bfa2'
  on-secondary-fixed: '#2b1705'
  on-secondary-fixed-variant: '#5c412b'
  tertiary-fixed: '#b2f0cb'
  tertiary-fixed-dim: '#97d4b0'
  on-tertiary-fixed: '#002112'
  on-tertiary-fixed-variant: '#125135'
  background: '#fff7fa'
  on-background: '#231822'
  surface-variant: '#f0ddec'
typography:
  display:
    fontFamily: Quicksand
    fontSize: 44px
    fontWeight: '700'
    lineHeight: 52px
    letterSpacing: -0.02em
  display-mobile:
    fontFamily: Quicksand
    fontSize: 32px
    fontWeight: '700'
    lineHeight: 40px
    letterSpacing: -0.01em
  headline-lg:
    fontFamily: Quicksand
    fontSize: 32px
    fontWeight: '700'
    lineHeight: 40px
  headline-lg-mobile:
    fontFamily: Quicksand
    fontSize: 26px
    fontWeight: '700'
    lineHeight: 34px
  headline-md:
    fontFamily: Quicksand
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
  headline-sm:
    fontFamily: Quicksand
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
  body-lg:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '400'
    lineHeight: 28px
  body-md:
    fontFamily: Inter
    fontSize: 15px
    fontWeight: '400'
    lineHeight: 22px
  body-sm:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 18px
  label-lg:
    fontFamily: Quicksand
    fontSize: 15px
    fontWeight: '700'
    lineHeight: 20px
  label-md:
    fontFamily: Quicksand
    fontSize: 13px
    fontWeight: '700'
    lineHeight: 18px
  label-sm:
    fontFamily: Quicksand
    fontSize: 11px
    fontWeight: '700'
    lineHeight: 14px
    letterSpacing: 0.04em
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  gutter: 1rem
  gutter-lg: 1.5rem
  margin: 1rem
  margin-md: 1.5rem
  margin-lg: 2.5rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 1rem
  space-lg: 1.5rem
  space-xl: 2rem
  space-2xl: 3rem
---

## Brand & Style

This design system expresses pure culinary delight, discovery, and warmth. Built for a Bangalore restaurant recommendation engine operating with Zomato integration, the visual personality is playful, appetizing, and approachable. It turns the everyday question of "What should we eat?" into an intuitive, tactile micro-game.

The core aesthetic marries a soft pastel palette with tactile sticker/kawaii sensibilities:
- **Rounded & Friendly**: Surfaces feature generous radii (16px to 24px), avoiding harsh clinical angles.
- **Subtle Plum Outlines**: Instead of stark black wireframes, a rich dark plum (`#3A2E39`) anchors the interface, providing grounded structure, crisp line-art detailing, and uncompromising WCAG AA compliance.
- **Tactile Softness**: Cards, chips, and floating elements suggest tangible, die-cut stickers placed on a warm cream canvas.
- **Delight & Spontaneity**: Micro-interactions are buoyant and responsive, giving food tags, rating badges, and cuisine cards a bouncy, joyous physical presence.

## Colors

The palette balances joyful, confectionery pastel tones with an ultra-deep plum neutral that guarantees readability and visual anchoring.

### Functional Palette
- **Canvas Base (`#FFF8F0`)**: Warm pastry cream used for global backdrops and nested container wells.
- **Primary / Blush Pink (`#FF9EBB`)**: Main call-to-actions, active filter states, heart/favorite triggers, and celebratory highlights.
- **Secondary / Soft Peach (`#FFD6B8`)**: Recommendation highlights, secondary buttons, warm tags, and discount chips.
- **Tertiary / Fresh Mint (`#A8E6C1`)**: Vegetarian markers, high-match recommendation scores, open-now indicators, and positive state badges.
- **Accent Lavender (`#D9CCF5`)**: Cuisines, late-night spots, and exploratory "surprise me" categories.
- **Accent Butter Yellow (`#FFE8A3`)**: Zomato review ratings, featured star badges, and trending alerts.
- **Accent Baby Blue (`#BEE3F8`)**: Delivery distance badges, Bangalore neighborhood chips (e.g., Indiranagar, Koramangala), and map interfaces.
- **Structural Neutral / Dark Plum (`#3A2E39`)**: Used for 100% of body text, primary icons, and structural 1.5px/2px die-cut borders. It offers deep, rich contrast against cream and pastel fills without the harshness of pure black `#000000`.
- **Pure Card White (`#FFFFFF`)**: Base fill for interactive restaurant cards to ensure maximum contrast beneath text and food photography.

## Typography

The typography pairs **Quicksand** for display, headings, and labels with **Inter** for descriptions, menu items, and long-form reviews. 

- **Quicksand**: Carries rounded terminals, radiating warmth and friendly informality. It transforms headlines and micro-tags into bouncy, legible signposts.
- **Inter**: Neutral, highly legible grotesque body face designed to keep dense restaurant menus, addresses, opening hours, and pricing tiers clear and effortless to scan.
- **Hierarchy Rules**: Headers must always use the Dark Plum (`#3A2E39`) neutral. Never set running body copy in colored pastels. Pastels are exclusively reserved for surface container fills, badges, and icon backdrops.

## Layout & Spacing

The layout uses a fluid responsive grid structured for quick scanning on mobile devices and multi-column discovery on desktop screens.

### Grid & Breakpoints
- **Mobile (< 640px)**: 4-column layout with `1rem` margins and `1rem` gutters. Cards render as full-width discovery tiles or horizontal swipe carousels.
- **Tablet (640px - 1024px)**: 8-column layout with `1.5rem` margins and `1.25rem` gutters. Feeds transition into 2-column card layouts.
- **Desktop (> 1024px)**: 12-column layout capped at a maximum width of `1280px` centered with dynamic margins (`margin-lg: 2.5rem`), supporting a 3-column discovery feed with a persistent filter sidebar.

### Spacing Philosophy
Rhythm is built on a 4px/8px modular scale. Dense data (e.g., timing, distance, price points) uses compact `space-xs` and `space-sm` gaps, while card interiors and section separators breathe with `space-lg` and `space-xl`.

## Elevation & Depth

This system intentionally rejects harsh realistic drop shadows in favor of **sticker-inspired tactile layering**:

1. **Die-Cut Outlines**: Every interactive card, floating pill, and active element is bounded by a crisp `1.5px` solid outline in Dark Plum (`#3A2E39`).
2. **Offset Hard/Soft Shadows (Tactile Sticker Lift)**:
   - **Resting Elevation**: `0px 3px 0px 0px rgba(58, 46, 57, 0.9), 0px 8px 16px -4px rgba(217, 204, 245, 0.45)`. This combines a small directional hard shelf in dark plum with an ambient pastel blur, giving the impression of thick cardstock.
   - **Hover / Active Elevation**: Upon hover, elements translate `-2px` on the Y-axis with an intensified offset: `0px 5px 0px 0px rgba(58, 46, 57, 0.95), 0px 12px 20px -4px rgba(255, 158, 187, 0.4)`.
   - **Pressed / Clicked**: Elements translate `+2px` downward, reducing the offset to `0px 1px 0px 0px rgba(58, 46, 57, 1)`.
3. **Surface Stacking**: Backgrounds begin at Cream `#FFF8F0`. Resting containers sit on Pure White `#FFFFFF`, with nested sub-sections (e.g., Zomato quote snippets or tip boxes) filled with pastel washes (`#FFD6B8` Peach, `#D9CCF5` Lavender, `#FFE8A3` Butter Yellow).

## Shapes

The shape system is friendly, soft, and organic:
- **Base Components (Cards, Modals)**: Master container radius is set between `16px` (`rounded-lg`) and `24px` (`rounded-xl`), creating pillow-like restaurant profiles.
- **Tags, Chips, & Buttons**: Use fully rounded pill silhouettes (`rounded-full` / `9999px`) to invite tapping and swiping.
- **Sticker Accents**: Decorative food badges (dosa, coffee cup, dim sum) sit within rounded squircle badges (`18px` radius) with a subtle 3-degree rotation tilt for an expressive, sticker-book feel.

## Components

### Buttons
- **Primary CTA ("Find Food", "View on Zomato")**: Blush Pink (`#FF9EBB`) background, `1.5px` solid Dark Plum (`#3A2E39`) border, Dark Plum text (`label-lg`), `rounded-full`. Soft plum offset shadow. Depresses slightly when pressed.
- **Secondary CTA ("Surprise Me", "Filter")**: Butter Yellow (`#FFE8A3`) or Cream background with `1.5px` Dark Plum border and matching Dark Plum typography.
- **Ghost / Tertiary**: Transparent surface with a soft Peach (`#FFD6B8`) hover wash, no border.

### Chips & Filter Pills
- **State - Inactive**: Pure White background, `1.5px` solid Dark Plum border, Dark Plum text (`label-md`), fully pill-shaped.
- **State - Active / Selected**: Colored fills by category—Mint (`#A8E6C1`) for veg/healthy, Lavender (`#D9CCF5`) for neighborhood, Peach (`#FFD6B8`) for vibes. Includes a tiny plum checkmark or food icon prefix.

### Restaurant Recommendation Cards
- **Structure**: Surface in Pure White, `20px` radius, bounded by a `1.5px` Dark Plum border and offset shadow.
- **Media Header**: Food image rounded at top corners (`18px`) with an overlay badge for Zomato Rating (Butter Yellow `#FFE8A3` pill with a Dark Plum star) and Price for Two (`₹₹`).
- **Body**: Quicksand Headline (`headline-sm`), distance/location chip in Baby Blue (`#BEE3F8`), cuisine labels in pastel pills.
- **Action Zone**: Direct deep-link anchor button: "Order via Zomato" with the characteristic Zomato badge icon.

### Form Inputs & Search Fields
- **Search Bar**: Generous `48px` pill-shaped input, Cream or White background, `1.5px` Dark Plum border, Quicksand placeholder text in plum with 60% opacity. Leading icon is an animated magnifying glass or fork-and-spoon icon.
- **Checkboxes & Radios**: 
  - Rounded squares (`6px` radius) for checkboxes, circles for radio buttons.
  - Border: `2px` Dark Plum.
  - Checked State: Mint (`#A8E6C1`) fill with a Dark Plum checkmark.

### Mood & Craving Selector (Custom Component)
- Horizontal carousel of sticker-style cards featuring illustrated food mascots with pastel background disks (Peach, Lavender, Mint). Tapping triggers a playful spring bounce micro-interaction that populates corresponding curated recommendations.