import { useI18n, translateProgress } from '../i18n';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Settings as SettingsIcon, Shield, Server, Zap, Globe, Key, LogOut, CheckCircle2, AlertTriangle, RefreshCw, Bookmark, Heart } from 'lucide-react';

const API_BASE = 'http://127.0.0.1:8000';
type Provider = '9router' | 'openrouter' | 'google' | 'custom';

interface Status {
  data_dir: string;
  session_configured: boolean;
  ai_configured: boolean;
  ai_key_configured: boolean;
  ai_provider: Provider;
  ai_model: string;
  ai_base_url: string;
  public_downloader_available: boolean;
}

interface AppBridge {
  openInstagramLogin?: () => Promise<{ success: boolean; username?: string; error?: string }>;
  importSession: () => Promise<boolean>;
  chooseDataDirectory: () => Promise<string | null>;
  copyArchive: (activate: boolean) => Promise<{ destination: string; files_verified: number } | null>;
  migrateArchive: (activate: boolean) => Promise<{ destination: string; migrated_files: number; rebased_paths: number } | null>;
  moveArchive: () => Promise<{ destination: string; migrated_files: number; rebased_paths: number } | null>;
  restartApp: () => Promise<boolean>;
  chooseExportDirectory: () => Promise<string | null>;
  saveDiagnostics: () => Promise<string | null>;
}

const detail = async (response: Response, fallback: string) => {
  try { return (await response.json()).detail || fallback; } catch { return fallback; }
};

const Settings = () => {
  const { t, language } = useI18n();
  const [status, setStatus] = useState<Status | null>(null);
  const [sessionInfo, setSessionInfo] = useState<{ configured: boolean; account_id?: string; is_paused?: boolean; paused_reason?: string } | null>(null);
  const [showCookieBox, setShowCookieBox] = useState(false);
  const [cookieSessionId, setCookieSessionId] = useState('');
  const [cookieDsUserId, setCookieDsUserId] = useState('');
  const [isConnectingCookie, setIsConnectingCookie] = useState(false);
  const [loginInProgress, setLoginInProgress] = useState(false);
  const [provider, setProvider] = useState<Provider>('9router');
  const [model, setModel] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [key, setKey] = useState('');
  const [models, setModels] = useState<string[]>([]);
  const [selectedDirectory, setSelectedDirectory] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [copyProgress, setCopyProgress] = useState('');
  const [exportDirectory, setExportDirectory] = useState('');
  const [importStarted, setImportStarted] = useState(false);
  const [exportPreview, setExportPreview] = useState<{ saved: number; liked: number; overlap: number; collections: number; invalid_links: number } | null>(null);
  const [qualityTarget, setQualityTarget] = useState(localStorage.getItem('qualityTarget') || 'high');
  const [dailyLimit, setDailyLimit] = useState(5000);
  const [proxies, setProxies] = useState('');
  const [downloadConcurrency, setDownloadConcurrency] = useState(1);

  const bridge = (window as Window & { appBridge?: AppBridge }).appBridge;

  const refresh = async () => {
    try {
      const response = await fetch(`${API_BASE}/settings/status`);
      if (!response.ok) throw new Error(t("سرویس برنامه در دسترس نیست"));
      const next: Status = await response.json();
      setStatus(next);
      setProvider(next.ai_provider);
      setModel(next.ai_model);
      if (next.ai_provider === 'custom') setBaseUrl(next.ai_base_url);

      const sessionRes = await fetch(`${API_BASE}/settings/session/info`);
      if (sessionRes.ok) {
        setSessionInfo(await sessionRes.json());
      }

      const appSettingsRes = await fetch(`${API_BASE}/settings/app`);
      if (appSettingsRes.ok) {
        const appSet = await appSettingsRes.json();
        if (appSet.daily_download_limit) setDailyLimit(appSet.daily_download_limit);
        if (appSet.proxies !== undefined) setProxies(appSet.proxies);
        if (appSet.download_concurrency) setDownloadConcurrency(appSet.download_concurrency);
      }
    } catch (error) { setMessage(String(error)); }
  };

  useEffect(() => { void refresh(); }, []);

  const handleInAppLogin = async () => {
    if (!bridge?.openInstagramLogin) {
      setMessage(t("ورود با مرورگر رسمی تنها در نسخه دسکتاپ فعال است."));
      return;
    }
    setLoginInProgress(true);
    setMessage(t("پنجره رسمی ورود به اینستاگرام باز شد. لطفاً در آن پنجره وارد حساب خود شوید..."));
    try {
      const res = await bridge.openInstagramLogin();
      if (res.success) {
        setMessage(language === 'fa' ? `اتصال رسمی اینستاگرام با موفقیت برقرار شد! کاربر: @${res.username || ''}` : `Instagram connected successfully! User: @${res.username || ''}`);
        await refresh();
      } else {
        setMessage(res.error || t("ورود به اینستاگرام لغو شد"));
      }
    } catch (err: any) {
      setMessage(err.message || String(err));
    } finally {
      setLoginInProgress(false);
    }
  };

  const handleCookieLogin = async () => {
    if (!cookieSessionId.trim()) {
      setMessage(t("لطفاً مقدار کوکی sessionid را وارد کنید."));
      return;
    }
    setIsConnectingCookie(true);
    try {
      const res = await fetch(`${API_BASE}/settings/session/cookie`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sessionid: cookieSessionId.trim(),
          ds_user_id: cookieDsUserId.trim() || undefined
        })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || t("خطا در اتصال کوکی"));
      setMessage(t(data.message || "نشست با موفقیت ثبت شد!"));
      setCookieSessionId('');
      setCookieDsUserId('');
      setShowCookieBox(false);
      await refresh();
    } catch (err: any) {
      setMessage(err.message || String(err));
    } finally {
      setIsConnectingCookie(false);
    }
  };

  const handleDisconnectSession = async () => {
    if (!confirm(t("آیا از قطع اتصال حساب اینستاگرام مطمئن هستید؟"))) return;
    try {
      await fetch(`${API_BASE}/settings/session`, { method: 'DELETE' });
      setMessage(t("اتصال حساب اینستاگرام قطع شد."));
      await refresh();
    } catch (err: any) {
      setMessage(err.message || String(err));
    }
  };

  const handleDirectSync = async (source: 'saved' | 'liked') => {
    try {
      const res = await fetch(`${API_BASE}/jobs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          job_type: 'discovery',
          params: { mode: 'recent', source, max_pages: 5 }
        })
      });
      if (!res.ok) throw new Error((await res.json()).detail || t("خطا در شروع همگام‌سازی"));
      setMessage(language === 'fa' ? `فرآیند دریافت ${source === 'saved' ? 'ذخیره‌ها' : 'لایک‌ها'} از اینستاگرام آغاز شد. پیشرفت را در داشبورد مشاهده کنید.` : `Direct sync of Instagram ${source === 'saved' ? 'saves' : 'likes'} started. Follow progress on dashboard.`);
    } catch (err: any) {
      setMessage(err.message || String(err));
    }
  };

  const importSession = async () => {
    try {
      if (!bridge) throw new Error(t("اتصال نسخهٔ دسکتاپ در دسترس نیست. نسخهٔ جدید را نصب کنید."));
      if (await bridge.importSession()) {
        setMessage(t("نشست رمزگذاری‌شده وارد شد."));
        await refresh();
      }
    } catch (error) { setMessage(String(error)); }
  };

  const chooseDirectory = async () => {
    try {
      if (!bridge) throw new Error(t("اتصال نسخهٔ دسکتاپ در دسترس نیست. نسخهٔ جدید را نصب کنید."));
      const selected = await bridge.chooseDataDirectory();
      if (selected) {
        setSelectedDirectory(selected);
        setMessage(t("مسیر ذخیره شد. برای استفاده برنامه را بازنشانی کنید. فایل‌های قبلی جابه‌جا نشده‌اند."));
      }
    } catch (error) { setMessage(String(error)); }
  };

  const copyArchive = async (activate: boolean) => {
    if (!bridge) { setMessage(t("اتصال نسخهٔ دسکتاپ در دسترس نیست")); return; }
    setBusy(true);
    setCopyProgress(t("آماده‌سازی نسخهٔ آرشیو..."));
    const timer = setInterval(async () => {
      try {
        const response = await fetch(`${API_BASE}/jobs`);
        const jobs = await response.json();
        const job = jobs.find((entry: { type: string; status: string }) => entry.type === 'storage' && ['QUEUED', 'RUNNING'].includes(entry.status));
        if (job) setCopyProgress(`${Math.round(job.progress || 0)}% · ${translateProgress(job.message || 'Copying', language)}`);
      } catch { /* backend status will be reported by the copy request */ }
    }, 1000);
    try {
      const result = await bridge.copyArchive(activate);
      if (result) {
        setMessage(`${activate ? t("نسخهٔ تأییدشده آماده است؛ برنامه را بازنشانی کنید") : t("پشتیبان تأییدشده ذخیره شد")}: ${result.destination} (${result.files_verified} ${t("فایل بررسی شد")}).`);
        if (activate) setSelectedDirectory(result.destination);
      }
    } catch (error) { setMessage(String(error)); }
    finally { clearInterval(timer); setBusy(false); setCopyProgress(''); }
  };

  const migrateArchive = async (activate: boolean) => {
    if (!bridge?.migrateArchive) { setMessage(t("اتصال نسخهٔ دسکتاپ در دسترس نیست")); return; }
    setBusy(true);
    setCopyProgress(t("آماده‌سازی و انتقال آرشیو..."));
    const timer = setInterval(async () => {
      try {
        const response = await fetch(`${API_BASE}/jobs`);
        const jobs = await response.json();
        const job = jobs.find((entry: { type: string; status: string }) => entry.type === 'migration' && ['QUEUED', 'RUNNING'].includes(entry.status));
        if (job) setCopyProgress(`${Math.round(job.progress || 0)}% · ${translateProgress(job.message || 'Migrating', language)}`);
      } catch { /* backend status will be reported */ }
    }, 1000);
    try {
      const result = await bridge.migrateArchive(activate);
      if (result) {
        setMessage(`${t("مهاجرت موفقیت‌آمیز بود:")} ${result.migrated_files} ${t("فایل رسانه منتقل و")} ${result.rebased_paths} ${t("مسیر دیتابیس به‌روزرسانی شد. برای اعمال کامل برنامه را بازنشانی کنید.")}`);
        await refresh();
      }
    } catch (error) { setMessage(String(error)); }
    finally { clearInterval(timer); setBusy(false); setCopyProgress(''); }
  };

  const moveArchive = async () => {
    if (!bridge?.moveArchive) { setMessage(t("اتصال نسخهٔ دسکتاپ در دسترس نیست")); return; }
    setBusy(true);
    setCopyProgress(t("آماده‌سازی و انتقال امن آرشیو فعلی به پوشه جدید..."));
    const timer = setInterval(async () => {
      try {
        const response = await fetch(`${API_BASE}/jobs`);
        const jobs = await response.json();
        const job = jobs.find((entry: { type: string; status: string }) => entry.type === 'migration' && ['QUEUED', 'RUNNING'].includes(entry.status));
        if (job) setCopyProgress(`${Math.round(job.progress || 0)}% · ${translateProgress(job.message || 'Moving', language)}`);
      } catch { /* backend status will be reported */ }
    }, 1000);
    try {
      const result = await bridge.moveArchive();
      if (result) {
        setMessage(`${t("انتقال موفقیت‌آمیز بود:")} ${result.migrated_files} ${t("فایل رسانه منتقل و")} ${result.rebased_paths} ${t("مسیر دیتابیس به‌روزرسانی شد. مسیر جدید جایگزین شد.")}`);
        setSelectedDirectory(result.destination);
        await refresh();
      }
    } catch (error) { setMessage(String(error)); }
    finally { clearInterval(timer); setBusy(false); setCopyProgress(''); }
  };

  const saveAppSettings = async () => {
    setBusy(true);
    try {
      const response = await fetch(`${API_BASE}/settings/app`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          daily_download_limit: Number(dailyLimit) || 5000,
          proxies: proxies.trim(),
          download_concurrency: Number(downloadConcurrency) || 1
        })
      });
      if (!response.ok) throw new Error(await detail(response, t("خطا در ذخیره تنظیمات دانلود")));
      setMessage(t("تنظیمات سرعت دانلود و پروکسی با موفقیت ذخیره شد."));
    } catch (error) { setMessage(String(error)); }
    finally { setBusy(false); }
  };

  const aiPayload = () => ({
    provider,
    model,
    api_key: key.trim() || null,
    base_url: provider === 'custom' ? baseUrl.trim() : null,
  });

  const loadModels = async () => {
    setBusy(true);
    try {
      const response = await fetch(`${API_BASE}/settings/ai/models`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(aiPayload()),
      });
      if (!response.ok) throw new Error(await detail(response, 'Could not load models'));
      const entries: { id: string; vision: boolean | null }[] = await response.json();
      setModels(entries.filter(entry => entry.vision !== false).map(entry => entry.id));
      setMessage(`${entries.length} ${t("مدل دریافت شد. مدل‌هایی که تصویر را قبول نمی‌کنند پنهان شدند.")}`);
    } catch (error) { setMessage(String(error)); }
    finally { setBusy(false); }
  };

  const saveAI = async () => {
    setBusy(true);
    try {
      const response = await fetch(`${API_BASE}/settings/ai`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(aiPayload()),
      });
      if (!response.ok) throw new Error(await detail(response, 'Could not save AI settings'));
      setKey('');
      setMessage(t("تنظیمات AI برای این حساب ویندوز ذخیره شد."));
      await refresh();
    } catch (error) { setMessage(String(error)); }
    finally { setBusy(false); }
  };

  const chooseExport = async () => {
    setBusy(true);
    try {
      if (!bridge) throw new Error(t("این قابلیت فقط در برنامهٔ دسکتاپ فعال است."));
      const directory = await bridge.chooseExportDirectory();
      if (!directory) return;
      setImportStarted(false);
      setMessage(t('در حال بررسی خروجی رسمی...'));
      const response = await fetch(`${API_BASE}/import/export/preview`, { method: 'POST',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ directory }) });
      if (!response.ok) throw new Error(await detail(response, t("خروجی قابل خواندن نیست")));
      setExportDirectory(directory);
      setExportPreview(await response.json());
    } catch (error) { setMessage(String(error)); }
    finally { setBusy(false); }
  };

  const importExport = async () => {
    setBusy(true);
    try {
      const response = await fetch(`${API_BASE}/jobs`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_type: 'export_import', params: { directory: exportDirectory } }) });
      if (!response.ok) throw new Error(await detail(response, t("ورود شروع نشد")));
      setImportStarted(true);
      setMessage(t("ورود آفلاین شروع شد. پیشرفت آن را در داشبورد ببینید."));
    } catch (error) { setMessage(String(error)); }
    finally { setBusy(false); }
  };

  const testAI = async () => {
    setBusy(true);
    try {
      const response = await fetch(`${API_BASE}/settings/ai/test`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(aiPayload()) });
      if (!response.ok) throw new Error(await detail(response, t("آزمون اتصال ناموفق بود")));
      setMessage((await response.json()).ok ? t("اتصال مدل تصویری برقرار است.") : t("مدل پاسخ معتبری نداد."));
    } catch (error) { setMessage(String(error)); }
    finally { setBusy(false); }
  };

  const changeProvider = (next: Provider) => {
    setKey('');
    setProvider(next);
    setModels([]);
    setModel(next === status?.ai_provider ? status.ai_model : '');
    setBaseUrl(next === 'custom' && status?.ai_provider === 'custom' ? status.ai_base_url : '');
  };

  return (
    <div className="view-container animate-fade-in" style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <h1 className="view-title"><SettingsIcon size={24} /> {t("تنظیمات")}</h1>
      {message && <p role="status">{message}</p>}
      {importStarted && <Link className="btn btn-primary" to="/">{t("رفتن به داشبورد برای دانلود")}</Link>}
      {message.includes(t("ورود آفلاین شروع شد")) && <Link className="btn btn-primary" to="/">{t("رفتن به دانلودها")}</Link>}

      <div className="card">
        <h2><Server size={18} /> {t("محل ذخیره‌سازی")}</h2>
        <p>{t("مسیر فعلی:")}<span dir="ltr">{status?.data_dir || t("در حال بارگذاری...")}</span></p>
        {selectedDirectory && <p>{t("پس از بازنشانی:")}<span dir="ltr">{selectedDirectory}</span></p>}
        <p>{t("می‌توانید آرشیو را کپی کنید، آرشیو موجود را انتخاب کنید یا داده‌ها را از پوشهٔ دیگر به این آرشیو انتقال دهید.")}</p>
        <p>{t("رسانه‌ها و کپشن‌ها فایل‌های خواندنی هستند؛ پوشه‌ای خصوصی انتخاب کنید. نشست برای همین کاربر ویندوز رمزگذاری می‌شود.")}</p>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginBottom: '8px' }}>
          <button className="btn btn-primary" disabled={busy} onClick={() => migrateArchive(true)}>{t("مهاجرت داده‌ها از پوشهٔ دیگر به آرشیو فعلی")}</button>
          <button className="btn" disabled={busy} onClick={() => moveArchive()}>{t("انتقال آرشیو فعلی به پوشه جدید")}</button>
          <button className="btn" disabled={busy} onClick={() => copyArchive(true)}>{t("کپی آرشیو و تغییر مسیر")}</button>
          <button className="btn" disabled={busy} onClick={() => copyArchive(false)}>{t("ساخت پشتیبان تأییدشده")}</button>
          <button className="btn" disabled={busy} onClick={chooseDirectory}>{t("انتخاب آرشیو موجود (بدون انتقال)")}</button>
          {selectedDirectory && <button className="btn btn-primary" onClick={() => bridge?.restartApp().catch(error => setMessage(String(error)))}>{t("بازنشانی برنامه")}</button>}
        </div>
        {copyProgress && <p role="status">{copyProgress}</p>}
      </div>

      <div className="card">
        <h2><Zap size={18} /> {t("سرعت دانلود و تنظیمات پروکسی")}</h2>
        <p>{t("برای دانلود پرسرعت و امن چند هزار پست بدون مسدود شدن اکانت، می‌توانید پروکسی تعریف کنید و سقف روزانه را افزایش دهید.")}</p>
        
        <label style={{ display: 'block', marginTop: '10px' }}>{t("سقف تعداد دانلود در هر ۲۴ ساعت")}<br />
          <input className="meta-input" type="number" min="10" max="50000" style={{ width: '120px' }}
            value={dailyLimit} onChange={e => setDailyLimit(Number(e.target.value) || 5000)} />
          <span style={{ fontSize: '12px', color: 'var(--text-secondary)', marginRight: '10px' }}>
            {t("پیش‌فرض: ۵۰۰۰ (امکان دانلود کل ۷۰۰۰ پست در کمتر از ۲ روز)")}
          </span>
        </label>

        <label style={{ display: 'block', marginTop: '12px' }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
            <Globe size={16} /> {t("لیست پروکسی‌ها (اختیاری اما بسیار موثر برای دانلود موازی و نامحدود)")}
          </span>
          <textarea className="meta-input" rows={4} style={{ width: '100%', fontFamily: 'monospace', fontSize: '13px' }}
            placeholder={`http://127.0.0.1:10809\nhttp://user:pass@proxy-ip:port\nsocks5://127.0.0.1:10808`}
            value={proxies} onChange={e => setProxies(e.target.value)} />
          <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
            {t("هر خط یک پروکسی. دانلودهای عمومی به صورت چرخشی از آن‌ها استفاده می‌کنند تا اینستاگرام IP را بلاک نکند.")}
          </span>
        </label>

        <div style={{ marginTop: '14px' }}>
          <button className="btn btn-primary" disabled={busy} onClick={saveAppSettings}>{t("ذخیره تنظیمات سرعت و پروکسی")}</button>
        </div>
      </div>

      <div className="card">
        <h2>{t("ورود خروجی رسمی اینستاگرام")}</h2>
        <p>{t("پوشهٔ your_instagram_activity را انتخاب کنید. پیش‌نمایش و ورود کاملاً آفلاین است؛ فایل JSON عکس یا ویدیو ندارد.")}</p>
        <button className="btn" disabled={busy} onClick={chooseExport}>{t("انتخاب پوشه و پیش‌نمایش")}</button>
        {exportDirectory && <p dir="ltr">{exportDirectory}</p>}
        {exportPreview && <>
          <p>{t("ذخیره‌شده:")}{exportPreview.saved} {t("· لایک‌شده:")}{exportPreview.liked} {t("· مشترک:")}{exportPreview.overlap} {t("· مجموعه:")}{exportPreview.collections} {t("· لینک نامعتبر:")}{exportPreview.invalid_links}</p>
          <button className="btn btn-primary" disabled={busy} onClick={importExport}>{t("وارد کردن فهرست")}</button>
        </>}
      </div>

      <div className="card">
        <h2>{t("آستانهٔ تشخیص کیفیت پایین")}</h2>
        <p>{t("دانلودر بهترین نسخهٔ موجود در روش انتخابی را می‌گیرد. این گزینه فقط تعیین می‌کند فایل‌ها از چه اندازه‌ای پایین‌تر برای ارتقا علامت بخورند؛ اندازهٔ بالاتر از نسخهٔ ارائه‌شده تضمین نمی‌شود.")}</p>
        <select className="filter-select" value={qualityTarget} onChange={event => { setQualityTarget(event.target.value); localStorage.setItem('qualityTarget', event.target.value); }}>
          <option value="high">{t("ارتقا اگر ضلع کوتاه کمتر از ۱۰۸۰ پیکسل باشد")}</option>
          <option value="hd">{t("ارتقا اگر ضلع کوتاه کمتر از ۷۲۰ پیکسل باشد")}</option>
        </select>
        <p>{t("برای فایل‌های موجود، از داشبورد «سنجش کیفیت» را اجرا کنید؛ سپس در صورت نیاز «ارتقای کیفیت» را دستی شروع کنید.")}</p>
      </div>

      <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '14px', border: sessionInfo?.configured ? '1px solid rgba(16, 185, 129, 0.3)' : '1px solid var(--border)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '10px' }}>
          <h2 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Shield size={20} color="var(--primary)" /> {t("حساب کاربری و نشست اینستاگرام")}
          </h2>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            {sessionInfo?.configured ? (
              <span className="badge" style={{ background: 'rgba(16, 185, 129, 0.15)', color: '#10b981', border: '1px solid rgba(16, 185, 129, 0.3)', display: 'flex', alignItems: 'center', gap: '5px' }}>
                <CheckCircle2 size={12} /> {t("متصل و معتبر")}
              </span>
            ) : (
              <span className="badge" style={{ background: 'rgba(245, 158, 11, 0.15)', color: '#f59e0b', border: '1px solid rgba(245, 158, 11, 0.3)', display: 'flex', alignItems: 'center', gap: '5px' }}>
                <AlertTriangle size={12} /> {t("حساب متصل نیست")}
              </span>
            )}
          </div>
        </div>

        {sessionInfo?.configured ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <div style={{ background: 'var(--bg-main)', padding: '14px', borderRadius: '8px', border: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '10px' }}>
              <div>
                <div style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text-main)' }}>
                  {t("شناسه حساب متصل:")} <code dir="ltr" style={{ color: 'var(--primary)', fontWeight: 700 }}>{sessionInfo.account_id || 'ID Active'}</code>
                </div>
                <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '4px' }}>
                  {sessionInfo.is_paused ? (
                    <span style={{ color: 'var(--error)' }}>{t("وضعیت: موقتاً به دلیل محدودیت اینستاگرام متوقف شده")} ({sessionInfo.paused_reason})</span>
                  ) : (
                    <span style={{ color: 'var(--success)' }}>{t("وضعیت: اتصال فعال، آماده برای دیسکاوری مستقیم و دانلود خصوصی")}</span>
                  )}
                </div>
              </div>
              <button 
                type="button" 
                className="btn btn-sm" 
                onClick={handleDisconnectSession}
                style={{ color: 'var(--error)', borderColor: 'rgba(239, 68, 68, 0.3)', display: 'flex', alignItems: 'center', gap: '6px' }}
              >
                <LogOut size={14} /> {t("خروج و قطع اتصال")}
              </button>
            </div>

            {/* Direct Sync Quick Triggers */}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px' }}>
              <button 
                className="btn btn-primary" 
                disabled={busy || sessionInfo.is_paused} 
                onClick={() => handleDirectSync('saved')}
                style={{ display: 'flex', alignItems: 'center', gap: '6px' }}
              >
                <Bookmark size={15} /> {t("همگام‌سازی مستقیم ذخیره‌ها (Sync Saved)")}
              </button>
              <button 
                className="btn" 
                disabled={busy || sessionInfo.is_paused} 
                onClick={() => handleDirectSync('liked')}
                style={{ display: 'flex', alignItems: 'center', gap: '6px' }}
              >
                <Heart size={15} /> {t("همگام‌سازی مستقیم لایک‌ها (Sync Liked)")}
              </button>
              {sessionInfo.is_paused && (
                <button 
                  className="btn" 
                  onClick={async () => {
                    await fetch(`${API_BASE}/instagram/resume`, { method: 'POST' });
                    await refresh();
                  }}
                  style={{ display: 'flex', alignItems: 'center', gap: '6px' }}
                >
                  <RefreshCw size={15} /> {t("رفع توقف موقت و ادامه")}
                </button>
              )}
            </div>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
            <p style={{ margin: 0, fontSize: '13px', color: 'var(--text-secondary)', lineHeight: 1.6 }}>
              {t("برای جلوگیری از فلگ شدن، بن یا چالش‌های امنیتی اینستاگرام، دو روش بدون پسورد و ۱۰۰٪ امن فراهم شده است:")}
            </p>

            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px' }}>
              {/* Method 1: Official In-App Login */}
              <button 
                type="button" 
                className="btn btn-primary" 
                onClick={handleInAppLogin} 
                disabled={loginInProgress}
                style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '10px 18px', fontWeight: 600 }}
              >
                <Globe size={16} /> 
                {loginInProgress ? t("در حال انتظار برای ورود...") : t("ورود رسمی از طریق پنجره اینستاگرام (پیشنهادی و امن)")}
              </button>

              {/* Method 2: Paste Cookie */}
              <button 
                type="button" 
                className="btn" 
                onClick={() => setShowCookieBox(!showCookieBox)}
                style={{ display: 'flex', alignItems: 'center', gap: '8px' }}
              >
                <Key size={16} /> {showCookieBox ? t("بستن کادر کوکی") : t("ورود با کوکی مرورگر (Cookie Login)")}
              </button>

              {/* Method 3: Import File */}
              <button 
                type="button" 
                className="btn" 
                onClick={importSession}
                style={{ display: 'flex', alignItems: 'center', gap: '6px' }}
              >
                {t("وارد کردن فایل session.enc")}
              </button>
            </div>

            {/* Manual Cookie Box */}
            {showCookieBox && (
              <div style={{ background: 'var(--bg-main)', padding: '16px', borderRadius: '8px', border: '1px solid var(--border)', display: 'flex', flexDirection: 'column', gap: '12px' }}>
                <div style={{ fontSize: '13px', fontWeight: 600 }}>{t("راهنمای دریافت کوکی از مرورگر (Chrome / Edge / Firefox):")}</div>
                <ol style={{ fontSize: '12px', color: 'var(--text-secondary)', paddingInlineStart: '20px', margin: 0, lineHeight: 1.8 }}>
                  <li>{t("در مرورگر خود به آدرس instagram.com بروید (جایی که در اکانت خود لاگین هستید).")}</li>
                  <li>{t("کلید F12 را فشار دهید تا پنجره Developer Tools باز شود.")}</li>
                  <li>{t("به تب Application (در فایرفاکس Storage) بروید و در منوی سمت چپ Cookies > https://www.instagram.com را انتخاب کنید.")}</li>
                  <li>{t("مقدار sessionid را کپی کرده و در کادر زیر قرار دهید.")}</li>
                </ol>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  <label style={{ fontSize: '12px', fontWeight: 600 }}>
                    {t("مقدار کوکی sessionid (الزامی):")}
                    <input 
                      type="text" 
                      className="meta-input" 
                      dir="ltr" 
                      placeholder={language === 'fa' ? "مثال: 68492048%3AKfJ9..." : "e.g. 68492048%3AKfJ9..."} 
                      value={cookieSessionId} 
                      onChange={e => setCookieSessionId(e.target.value)}
                      style={{ width: '100%', marginTop: '4px', fontFamily: 'monospace', fontSize: '12px' }}
                    />
                  </label>
                  <label style={{ fontSize: '12px', fontWeight: 600 }}>
                    {t("مقدار ds_user_id (اختیاری):")}
                    <input 
                      type="text" 
                      className="meta-input" 
                      dir="ltr" 
                      placeholder={language === 'fa' ? "شناسه عددی اکانت (در صورت خالی بودن خودکار استخراج می‌شود)" : "Numeric account ID (extracted automatically if left blank)"} 
                      value={cookieDsUserId} 
                      onChange={e => setCookieDsUserId(e.target.value)}
                      style={{ width: '100%', marginTop: '4px', fontFamily: 'monospace', fontSize: '12px' }}
                    />
                  </label>
                </div>
                <div style={{ display: 'flex', gap: '8px', marginTop: '4px' }}>
                  <button 
                    type="button" 
                    className="btn btn-primary btn-sm" 
                    onClick={handleCookieLogin}
                    disabled={isConnectingCookie || !cookieSessionId.trim()}
                  >
                    {isConnectingCookie ? t("در حال اتصال...") : t("ثبت و اتصال به اینستاگرام")}
                  </button>
                  <button 
                    type="button" 
                    className="btn btn-sm" 
                    onClick={() => setShowCookieBox(false)}
                  >
                    {t("انصراف")}
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      <div className="card">
        <h2><Shield size={18} /> {t("تحلیل AI")}</h2>
        <p>{t("ارائه‌دهنده:")}{status?.ai_provider || t("در حال بارگذاری...")} {t("· کلید:")}{status?.ai_key_configured ? t("آماده") : t("تنظیم‌نشده")}</p>
        <label>{t("ارائه‌دهنده")}<br />
          <select className="filter-select" value={provider} disabled={busy} onChange={event => changeProvider(event.target.value as Provider)}>
            <option value="9router">9Router</option>
            <option value="openrouter">OpenRouter</option>
            <option value="google">Google Gemini</option>
            <option value="custom">{t('Custom OpenAI-compatible API')}</option>
          </select>
        </label>
        {provider === 'custom' && <label style={{ display: 'block', marginTop: '12px' }}>{t('Base URL')}<br />
          <input className="meta-input" value={baseUrl} onChange={event => setBaseUrl(event.target.value)} placeholder="https://example.com/v1" />
        </label>}
        <label style={{ display: 'block', marginTop: '12px' }}>{t("کلید API (برای نگه‌داشتن کلید فعلی خالی بگذارید)")}<br />
          <input className="meta-input" type="password" autoComplete="off" value={key} onChange={event => setKey(event.target.value)} placeholder={t('API key')} />
        </label>
        <p>{t("تحلیل، نمونه‌هایی از تصویر و کپشن را به ارائه‌دهندهٔ انتخاب‌شده می‌فرستد. مدل دارای ورودی تصویر انتخاب کنید.")}</p>
        <label style={{ display: 'block', marginTop: '12px' }}>{t("مدل تصویری")}<br />
          <input className="meta-input" list="ai-models" value={model} onChange={event => setModel(event.target.value)} placeholder={t('Load models or enter a model ID')} />
          <datalist id="ai-models">{models.map(id => <option value={id} key={id} />)}</datalist>
        </label>
        <div style={{ display: 'flex', gap: '10px', marginTop: '12px' }}>
          <button className="btn" onClick={loadModels} disabled={busy}>{busy ? t("در حال کار...") : t("دریافت مدل‌ها")}</button>
          <button className="btn btn-primary" onClick={saveAI} disabled={busy || !model.trim()}>{t("ذخیره تنظیمات AI")}</button>
          <button className="btn" onClick={testAI} disabled={busy || !model.trim()}>{t("آزمون اتصال مدل تصویری")}</button>
        </div>
        <p>{t("آزمون فقط یک تصویر مصنوعی یک‌پیکسلی می‌فرستد؛ ممکن است هزینهٔ اندکی داشته باشد.")}</p>
      </div>
      <div className="card">
        <h2>{t("گزارش پشتیبانی")}</h2>
        <p>{t("فقط شمارش وضعیت‌ها و نوع کارها ذخیره می‌شود؛ کپشن، شناسه، مسیر فایل، کلید و توکن در گزارش نیست.")}</p>
        <button className="btn" onClick={async () => { try { if (!bridge) throw new Error(t("فقط در نسخهٔ دسکتاپ")); const path = await bridge.saveDiagnostics(); if (path) setMessage(`${t("گزارش ذخیره شد:")} ${path}`); } catch (error) { setMessage(String(error)); } }}>{t("ذخیره گزارش بدون اطلاعات محرمانه")}</button>
      </div>
    </div>
  );
};

export default Settings;
