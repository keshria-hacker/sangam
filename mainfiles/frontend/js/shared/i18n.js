/**
 * Minimal i18n — t() with en/hi dictionaries (Sangam-native, Phase 5).
 *
 * Usage: t('new_chat') → "New chat" (or Hindi if lang is 'hi').
 * Wire: setLang(getSetting('language')) on app start.
 */
const STRINGS = {
  en: {
    new_chat: 'New chat',
    settings: 'Settings',
    send: 'Send message',
    stop: 'Stop generating',
    close: 'Close',
    cancel: 'Cancel',
    delete: 'Delete',
    save: 'Save',
    search: 'Search',
    home: 'Home',
    chat: 'Chat',
    agents: 'Agents',
    knowledge: 'Knowledge',
    create: 'Create',
    code: 'Code',
    learn: 'Learn',
    library: 'Library',
    insights: 'Insights',
    message_sangam: 'Message Sangam…',
    skip_to_conversation: 'Skip to conversation',
    toggle_theme: 'Toggle theme',
    command_palette: 'Command palette',
    collapse_sidebar: 'Collapse sidebar',
    expand_sidebar: 'Expand sidebar',
  },
  hi: {
    new_chat: 'नई चैट',
    settings: 'सेटिंग्स',
    send: 'संदेश भेजें',
    stop: 'रोकें',
    close: 'बंद करें',
    cancel: 'रद्द करें',
    delete: 'हटाएं',
    save: 'सहेजें',
    search: 'खोजें',
    home: 'होम',
    chat: 'चैट',
    agents: 'एजेंट',
    knowledge: 'ज्ञान',
    create: 'बनाएं',
    code: 'कोड',
    learn: 'सीखें',
    library: 'लाइब्रेरी',
    insights: 'इनसाइट्स',
    message_sangam: 'संगम को संदेश…',
    skip_to_conversation: 'वार्तालाप पर जाएं',
    toggle_theme: 'थीम बदलें',
    command_palette: 'कमांड पैलेट',
    collapse_sidebar: 'साइडबार छिपाएं',
    expand_sidebar: 'साइडबार दिखाएं',
  },
};

let lang = 'en';

export function setLang(l) {
  if (STRINGS[l]) {
    lang = l;
    document.documentElement.setAttribute('lang', l === 'hi' ? 'hi' : 'en');
  }
}

export function getLang() { return lang; }

export function t(key) {
  return (STRINGS[lang] && STRINGS[lang][key]) || STRINGS.en[key] || key;
}
