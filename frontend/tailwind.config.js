import plugin from 'tailwindcss/plugin'

// All visual values live here. Components use named utilities or these variables.
const light = {
  canvas: '#FBFCFF', surface: '#FFFFFF', subtle: '#F4F6FA',
  line: '#E4E8F0', 'line-strong': '#A8B4C8', ink: '#171B24', muted: '#687385',
  primary: '#2F6FED', 'primary-hover': '#255BD0', 'primary-soft': '#EDF3FF',
  'on-primary': '#FFFFFF', 'download-fill': 'rgb(255 255 255 / 0.15)',
  error: '#B33B35', 'error-soft': '#FAF0EE', 'error-line': '#D7A19B',
  overlay: 'rgb(23 27 36 / 0.35)',
  focus: 'rgb(47 111 237 / 0.12)',
}
const dark = {
  canvas: '#131720', surface: '#1C2230', subtle: '#242D3E',
  line: '#344056', 'line-strong': '#76839C', ink: '#F0F3FA', muted: '#A8B3C8',
  primary: '#8DAAFF', 'primary-hover': '#ACC1FF', 'primary-soft': '#263759',
  'on-primary': '#101B38', 'download-fill': 'rgb(16 27 56 / 0.15)',
  error: '#F09289', 'error-soft': '#382622', 'error-line': '#805149',
  overlay: 'rgb(0 0 0 / 0.48)',
  focus: 'rgb(141 170 255 / 0.14)',
}
const motion = {
  enter: '220ms', exit: '150ms', elastic: '320ms', attention: '1600ms',
  'ease-enter': 'ease-out', 'ease-exit': 'ease-in',
  'ease-elastic': 'cubic-bezier(0.34, 1.35, 0.64, 1)',
  lift: '8px', 'pulse-opacity': '0.8', 'check-scale': '0.88',
  'dim-opacity': '0.9',
}
const variables = values => Object.fromEntries(
  Object.entries(values).map(([key, value]) => [`--ui-${key}`, value]),
)

export default {
  theme: {
    colors: {
      transparent: 'transparent', current: 'currentColor',
      ...Object.fromEntries(Object.keys(light).map(key => [key, `var(--ui-${key})`])),
    },
    fontFamily: {
      sans: ['"PingFang SC"', '"Source Han Sans SC"', '"Noto Sans SC"', '"Microsoft YaHei"', 'system-ui', '-apple-system', '"Segoe UI"', 'sans-serif'],
      mono: ['ui-monospace', 'SFMono-Regular', 'Consolas', 'Menlo', 'monospace'],
    },
    fontSize: {
      hero: ['48px', { lineHeight: '64px' }],
      'hero-mobile': ['36px', { lineHeight: '44px' }],
      'hero-compact': ['28px', { lineHeight: '36px' }],
      quality: ['18px', { lineHeight: '28px' }],
      title: ['18px', { lineHeight: '28px' }],
      section: ['18px', { lineHeight: '28px' }],
      input: ['18px', { lineHeight: '28px' }],
      body: ['15px', { lineHeight: '24px' }],
      caption: ['13px', { lineHeight: '20px' }],
      micro: ['13px', { lineHeight: '20px' }],
    },
    fontWeight: { normal: '400', medium: '500', semibold: '600' },
    letterSpacing: { normal: '0', headline: '-0.035em' },
    spacing: {
      0: '0px', 2: '8px', 4: '16px', 6: '24px', 8: '32px',
      12: '48px', 16: '64px', 20: '80px', 24: '96px', 32: '128px',
      header: '64px', composer: '64px', 'composer-mobile': '64px',
      'page-block': 'clamp(16px, 3dvh, 32px)',
      'header-compact': '56px', footer: '48px', 'footer-compact': '40px',
      logo: '40px', badge: '32px',
      touch: '48px', icon: '20px', indicator: '24px', progress: '4px',
      'home-feedback': '70px',
    },
    borderRadius: { none: '0px', control: '14px', panel: '14px', pill: '999px' },
    borderWidth: { DEFAULT: '1px', 0: '0px' },
    boxShadow: { none: 'none', focus: '0 0 0 3px var(--ui-focus)', input: '0 2px 4px rgb(23 27 36 / 0.04)' },
    screens: { sm: '640px', md: '768px', lg: '1024px', xl: '1280px', '2xl': '1536px' },
    extend: {
      maxWidth: { workspace: '920px', 'input-area': '680px', 'result-panel': '960px', topbar: '1040px', 'format-option': '320px' },
      maxHeight: { 'result-height': 'calc(100dvh - 32px)' },
      width: {
        thumbnail: '280px', 'thumbnail-mobile': '96px',
        'result-frame': 'calc(100% - 32px)',
        parse: '160px', 'parse-mobile': '104px', paste: '48px', download: '176px',
        'nav-item': '128px', 'nav-start': '192px', 'nav-start-mobile': '144px',
        'help-action': '128px',
      },
      minHeight: { 'format-card': '88px', 'parse-status': '64px', 'download-bar': '80px', 'guide-step': '48px', 'guide-step-compact': '40px', 'home-details': '280px', 'home-details-compact': '240px', 'home-details-short': '152px' },
      aspectRatio: { video: '16 / 9', preview: '4 / 3' },
      gridTemplateColumns: {
        header: 'minmax(0, 1fr) auto',
        navigation: 'minmax(0, 1fr) auto minmax(0, 1fr)',
        summary: '280px minmax(0, 1fr)',
        'composer-mobile': '104px minmax(0, 1fr)',
        'format-content': 'minmax(0, 1fr) auto',
        'formats-four': 'repeat(4, minmax(0, 1fr))',
        'formats-three': 'repeat(3, minmax(0, 1fr))',
        'formats-two': 'repeat(2, minmax(0, 1fr))',
        'guide-five': 'repeat(5, minmax(0, 1fr))',
        'help-two': 'minmax(0, 1fr) minmax(0, 1fr)',
      },
      transitionDuration: {
        enter: 'var(--ui-enter)', exit: 'var(--ui-exit)', elastic: 'var(--ui-elastic)',
      },
      transitionTimingFunction: {
        enter: 'var(--ui-ease-enter)', exit: 'var(--ui-ease-exit)', elastic: 'var(--ui-ease-elastic)',
      },
      transitionProperty: {
        feedback: 'border-color, background-color, color, box-shadow, opacity, transform',
        expand: 'height, opacity', progress: 'width',
      },
      outlineWidth: { focus: '2px' }, outlineOffset: { focus: '2px' },
      textUnderlineOffset: { link: '4px' },
      zIndex: { download: '10', 'dialog-header': '20' },
      opacity: { subdued: 'var(--ui-dim-opacity)', disabled: '0.55' },
    },
  },
  plugins: [plugin(({ addBase }) => addBase({
    ':root': { ...variables(light), ...variables(motion), colorScheme: 'light' },
    '@media (prefers-color-scheme: dark)': {
      ':root': { ...variables(dark), colorScheme: 'dark' },
    },
    '@media (prefers-reduced-motion: reduce)': {
      ':root': {
        '--ui-lift': '0px', '--ui-pulse-opacity': '1', '--ui-check-scale': '1',
        '--ui-ease-elastic': 'ease-out',
      },
      '.expand-enter-active, .expand-leave-active, .rise-enter-active, .rise-leave-active, .check-enter-active, .check-leave-active, .button-feedback, .transition-feedback, .format-card, .quiet-button, .primary-button': {
        transitionProperty: 'opacity !important', transform: 'none !important',
      },
      '.progress-fill': { transition: 'none !important' },
    },
  }))],
}
