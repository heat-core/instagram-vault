import { useI18n } from '../i18n';
import { NavLink } from 'react-router-dom';
import { Home, DownloadCloud, Brain, LayoutGrid, Settings, AlertCircle, Link2 } from 'lucide-react';
// Note: lucide-react doesn't have ImageLibrary, let's use Images instead.

import { Images } from 'lucide-react';

const Sidebar = () => {
  const { t, language, setLanguage } = useI18n();
  return (
    <div className="sidebar">
      <div className="sidebar-title">Archive.io</div>
      
      <NavLink to="/" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`} end>
        <Home size={20} className="nav-icon" /> {t("داشبورد")}</NavLink>
      
      <NavLink to="/library" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
        <Images size={20} className="nav-icon" /> {t("کتابخانه")}</NavLink>
      
      <NavLink to="/downloads" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
        <DownloadCloud size={20} className="nav-icon" /> {t("دانلودها")}</NavLink>

      <NavLink to="/quick-download" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
        <Link2 size={20} className="nav-icon" /> {t("دانلود با لینک")}</NavLink>
      
      <NavLink to="/review" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
        <Brain size={20} className="nav-icon" /> {t("بررسی هوش مصنوعی")}</NavLink>
      
      <NavLink to="/categories" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
        <LayoutGrid size={20} className="nav-icon" /> {t("دسته‌بندی‌ها")}</NavLink>
      
      <NavLink to="/errors" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
        <AlertCircle size={20} className="nav-icon" /> {t("خطاها")}</NavLink>

      <div style={{ flex: 1 }}></div>

      <label className="language-control">
        <span>{t('زبان')}</span>
        <select aria-label={t('زبان')} value={language} onChange={event => setLanguage(event.target.value as 'fa' | 'en')}>
          <option value="fa">فارسی</option>
          <option value="en">English</option>
        </select>
      </label>

      <NavLink to="/settings" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
        <Settings size={20} className="nav-icon" /> {t("تنظیمات")}</NavLink>
    </div>
  );
};

export default Sidebar;
