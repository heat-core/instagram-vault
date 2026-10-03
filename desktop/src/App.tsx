import { HashRouter, Routes, Route } from 'react-router-dom';
import Sidebar from './components/Sidebar';
import Dashboard from './views/Dashboard';
import Library from './views/Library';
import Downloads from './views/Downloads';
import QuickDownload from './views/QuickDownload';
import AIReview from './views/AIReview';
import Categories from './views/Categories';
import Errors from './views/Errors';
import Settings from './views/Settings';
import { I18nProvider, useI18n } from './i18n';

function AppContent() {
  const { language } = useI18n();
  return (
    <HashRouter>
      <div className="app-container" dir={language === 'fa' ? 'rtl' : 'ltr'} lang={language}>
        <Sidebar />
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/library" element={<Library />} />
          <Route path="/downloads" element={<Downloads />} />
          <Route path="/quick-download" element={<QuickDownload />} />
          <Route path="/review" element={<AIReview />} />
          <Route path="/categories" element={<Categories />} />
          <Route path="/errors" element={<Errors />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </div>
    </HashRouter>
  );
}

function App() {
  return <I18nProvider><AppContent /></I18nProvider>;
}

export default App;
