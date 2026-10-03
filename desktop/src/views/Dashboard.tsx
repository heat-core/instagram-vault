import { useI18n, translateProgress } from '../i18n';
import { useEffect, useState } from 'react';
import { Play, Square, RefreshCcw } from 'lucide-react';
import { Link } from 'react-router-dom';

interface Stats {
  TOTAL?: number;
  DISCOVERED?: number;
  DOWNLOAD_PENDING?: number;
  DOWNLOAD_OK?: number;
  DOWNLOAD_FAILED?: number;
  ANALYSIS_PENDING?: number;
  ANALYSIS_OK?: number;
  ANALYSIS_FAILED?: number;
  REVIEW_REQUIRED?: number;
  UNAVAILABLE?: number;
  MISSING_LOCAL?: number;
  APPROVED?: number;
  ORGANIZED?: number;
  SAVED_PENDING?: number;
  LIKED_PENDING?: number;
  DOWNLOAD_DAILY_LIMIT?: number;
  DOWNLOAD_DAILY_REMAINING?: number;
  DOWNLOAD_DAILY_RESET_AT?: number | null;
}

interface Job {
  id: string;
  type: string;
  status: string;
  progress: number;
  message: string;
  created_at: number;
  updated_at: number;
}

const API_BASE = 'http://127.0.0.1:8000';

const Dashboard = () => {
  const { t, language } = useI18n();
  const [stats, setStats] = useState<Stats>({});
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [instagramPause, setInstagramPause] = useState<string | null>(null);
  const [actionError, setActionError] = useState('');
  const [aiBatchSize, setAiBatchSize] = useState(100);
  const [downloadSource, setDownloadSource] = useState('saved');
  const [downloadCollection, setDownloadCollection] = useState('');
  const [downloadBatch, setDownloadBatch] = useState(50);
  const [continuousDownload, setContinuousDownload] = useState(true);
  const [continuousAI, setContinuousAI] = useState(true);
  const [downloadMethod, setDownloadMethod] = useState(localStorage.getItem('downloadMethod') || 'auto');
  const [collections, setCollections] = useState<{ name: string; count: number }[]>([]);
  const [checkpoint, setCheckpoint] = useState<{ historical_complete?: number; historical_scan_cursor?: string | null; recent_scan_cursor?: string | null } | null>(null);
  const [latestSync, setLatestSync] = useState<{ id: string; mode: string; started_at: number; pages: number; discovered: number; checked: number; duplicates: number; downloaded: number; download_failed: number; outcome: string } | null>(null);
  const [publicDownloaderAvailable, setPublicDownloaderAvailable] = useState(false);

  const fetchInstagramStatus = async () => {
    try {
      const res = await fetch(`${API_BASE}/instagram/status`);
      if (res.ok) { const data = await res.json(); setInstagramPause(data.paused_reason); setCheckpoint(data.checkpoint); }
    } catch (e) {
      console.error('Failed to fetch Instagram status', e);
    }
  };

  const fetchStats = async () => {
    try {
      const res = await fetch(`${API_BASE}/stats`);
      const data = await res.json();
      setStats(data);
    } catch (e) {
      console.error("Failed to fetch stats", e);
    }
  };

  const fetchJobs = async () => {
    try {
      const res = await fetch(`${API_BASE}/jobs`);
      const data = await res.json();
      setJobs(data);
    } catch (e) {
      console.error("Failed to fetch jobs", e);
    }
  };

  const fetchSync = async () => {
    try { const res = await fetch(`${API_BASE}/sync/runs?limit=1`); if (res.ok) setLatestSync((await res.json())[0] || null); } catch { /* offline */ }
  };

  useEffect(() => {
    const loadData = async () => {
      await fetchStats();
      await fetchJobs();
      await fetchInstagramStatus();
      await fetchSync();
      try {
        const res = await fetch(`${API_BASE}/settings/status`);
        if (res.ok) setPublicDownloaderAvailable((await res.json()).public_downloader_available === true);
      } catch { /* downloader availability is shown as unavailable */ }
      try { const res = await fetch(`${API_BASE}/import/export/collections`); if (res.ok) setCollections(await res.json()); } catch { /* offline */ }
      setLoading(false);
    };
    
    loadData();
    // Poll for updates every 3 seconds
    const interval = setInterval(() => {
      fetchStats();
      fetchJobs();
      fetchInstagramStatus();
      fetchSync();
    }, 3000);
    
    return () => clearInterval(interval);
  }, []);

  const startJob = async (jobType: string, params: Record<string, string | number | boolean> = {}) => {
    try {
      setActionError('');
      const res = await fetch(`${API_BASE}/jobs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_type: jobType, params })
      });
      if (!res.ok) throw new Error((await res.json()).detail || 'Could not start job');
      fetchJobs(); // Update immediately
    } catch (e) {
      setActionError(String(e));
      console.error("Failed to start job", e);
    }
  };

  const resumeInstagram = async () => {
    const res = await fetch(`${API_BASE}/instagram/resume`, { method: 'POST' });
    if (res.ok) fetchInstagramStatus();
    else setActionError('Could not resume Instagram access');
  };

  const cancelJob = async (jobId: string) => {
    try {
      await fetch(`${API_BASE}/jobs/${jobId}/cancel`, { method: 'POST' });
      fetchJobs();
    } catch (e) {
      console.error("Failed to cancel job", e);
    }
  };

  const retryFailures = async (kind: 'analysis' | 'download') => {
    const path = kind === 'analysis' ? '/posts/retry-analysis' : '/posts/retry-failed';
    const res = await fetch(`${API_BASE}${path}`, { method: 'POST' });
    if (res.ok) fetchStats(); else setActionError(`Could not retry ${kind} failures`);
  };

  if (loading) {
    return <div className="main-content">{t("در حال بارگذاری...")}</div>;
  }

  const activeJobs = jobs.filter(j => j.status === 'RUNNING' || j.status === 'QUEUED');
  const readyCount = downloadCollection ? null
    : downloadSource === 'saved' ? stats.SAVED_PENDING || 0
    : downloadSource === 'liked' ? stats.LIKED_PENDING || 0 : stats.DISCOVERED || 0;
  const effectiveDownloader = downloadMethod === 'public' && publicDownloaderAvailable ? 'public' : 'session';
  const dailyRemaining = stats.DOWNLOAD_DAILY_REMAINING;
  const dailyReset = stats.DOWNLOAD_DAILY_RESET_AT
    ? new Date(stats.DOWNLOAD_DAILY_RESET_AT * 1000).toLocaleString(language === 'fa' ? 'fa-IR' : 'en-US') : '';
  const downloadParams = { batch_size: continuousDownload ? 0 : downloadBatch, continuous: continuousDownload, source: downloadSource,
    downloader: effectiveDownloader,
    quality_target: localStorage.getItem('qualityTarget') || 'high',
    ...(downloadCollection ? { collection: downloadCollection } : {}) };

  return (
    <div className="main-content animate-fade-in">
      <h1 className="view-title">{t("داشبورد")}</h1>
      {instagramPause && (
        <div className="card" role="alert" style={{ marginBottom: '16px' }}>
          {t("دسترسی اینستاگرام متوقف شده است:")}{instagramPause}{t(". پیش از ادامه حساب را در برنامهٔ رسمی بررسی کنید.")}<button className="btn" style={{ marginLeft: '12px' }} onClick={resumeInstagram}>{t("ادامهٔ دستی")}</button>
        </div>
      )}
      {actionError && <p role="alert" style={{ color: 'var(--error)' }}>{actionError}</p>}
      
      <div style={{ marginBottom: '20px', display: 'flex', flexWrap: 'wrap', gap: '10px' }}>
        <button className="btn btn-primary" disabled={!!instagramPause || readyCount === 0 || activeJobs.some(job => job.type === 'export_import')}
          onClick={async () => {
            if (dailyRemaining === 0) {
              await fetch(`${API_BASE}/settings/reset-limit`, { method: 'POST' });
              await fetchStats();
            }
            startJob('download', downloadParams);
          }}>
          <Play size={16} /> {continuousDownload ? t("دانلود پیوسته (تا پایان یا خطا)") : t("دانلود نوبت بعدی")}{readyCount !== null && ` (${readyCount} ${t("مورد آماده")})`}</button>
        <Link className="btn" to="/library?source=saved&status=DISCOVERED">{t('دیدن پست‌های ذخیرهٔ آماده')}</Link>
        {dailyRemaining === 0 && <div role="status" className="card" style={{ flexBasis: '100%', margin: '10px 0', display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: '10px' }}>
          <span>{t('سقف داخلی دانلود در ۲۴ ساعت اخیر تکمیل شده است؛ هر تلاش ناموفق هم شمرده می‌شود. موارد در صف می‌مانند و بعد از زمان زیر دوباره امکان تلاش هست:')} {dailyReset}</span>
          <button className="btn btn-primary" onClick={async () => {
            await fetch(`${API_BASE}/settings/reset-limit`, { method: 'POST' });
            fetchStats();
          }}>{t("رفع محدودیت و ادامه دانلود")}</button>
        </div>}
        <details style={{ flexBasis: '100%' }}>
        <summary style={{ cursor: 'pointer', color: 'var(--text-secondary)', padding: '8px 0' }}>{t('ابزارهای بیشتر')}</summary>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px', paddingTop: '8px' }}>
        <button className="btn" disabled={!!instagramPause} onClick={() => startJob('discovery', { mode: 'recent' })}>
          <RefreshCcw size={16} /> {t("بررسی ذخیره‌های جدید")}</button>
        <button className="btn" disabled={!!instagramPause || !!checkpoint?.historical_complete} onClick={() => startJob('discovery', { mode: 'history' })}>
          <RefreshCcw size={16} /> {t("ادامهٔ تاریخچه")}</button>
        <button className="btn" onClick={() => startJob('quality_scan')}>{t("سنجش کیفیت فایل‌های فعلی")}</button>
        <button className="btn" disabled={!!instagramPause} onClick={() => startJob('download', { ...downloadParams, upgrade: true })}>{t("تلاش برای ارتقای کیفیت")}</button>
        <button className="btn" onClick={() => startJob('analysis', { batch_size: continuousAI ? 0 : aiBatchSize, continuous: continuousAI })}>
          <Play size={16} /> {continuousAI ? t("تحلیل AI پیوسته (تا پایان)") : t("تحلیل AI")}</button>
        <label style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer', fontSize: '13px' }}><input type="checkbox" checked={continuousAI} onChange={e => setContinuousAI(e.target.checked)} style={{ accentColor: 'var(--primary)' }} />{t("تحلیل پیوسته تا پایان")}</label>
        {!continuousAI && <label style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>{t("پست هر نوبت AI")}<input className="meta-input" type="number" min="1" max="1000" value={aiBatchSize}
            style={{ width: '78px' }} onChange={event => setAiBatchSize(Math.min(1000, Math.max(1, Number(event.target.value) || 1)))} />
        </label>}
        <button className="btn" onClick={() => startJob('taxonomy')}>
          <Play size={16} /> {t("ساخت دسته‌بندی")}</button>
        <button className="btn" onClick={() => startJob('integrity')}>
          <RefreshCcw size={16} /> {t("بررسی سلامت فایل‌ها")}</button>
        </div>
        </details>
      </div>
      <p>{t('خروجی رسمی فقط فهرست و اطلاعات پست را دارد؛ برای گرفتن فایل رسانه، بعد از پایان ورود این دکمه را بزنید.')}</p>
      <div className="card" style={{ marginBottom: '20px' }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '12px' }}>
          <span style={{ color: 'var(--text-secondary)' }}>
            {t("تلاش‌های باقی‌مانده طبق سقف برنامه در بازهٔ ۲۴ ساعته:")} <strong style={{ color: 'var(--text-primary)' }}>{dailyRemaining ?? '—'} / {stats.DOWNLOAD_DAILY_LIMIT || 5000}</strong>
          </span>
          <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px' }}>
            <span style={{ color: 'var(--text-secondary)' }}>{t("روش دانلود")}:</span>
            <select className="filter-select" value={effectiveDownloader} onChange={e => {
              setDownloadMethod(e.target.value); localStorage.setItem('downloadMethod', e.target.value);
            }}>
              <option value="session">{t("نشست اینستاگرام · پست‌های خصوصی و عمومی")}</option>
              <option value="public" disabled={!publicDownloaderAvailable}>{t("عمومی · بدون کوکی حساب")}{!publicDownloaderAvailable ? ` · ${t('در این نسخه موجود نیست')}` : ''}</option>
            </select>
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px' }}>
            <span style={{ color: 'var(--text-secondary)' }}>{t("منبع")}:</span>
            <select className="filter-select" value={downloadSource} onChange={e => setDownloadSource(e.target.value)}>
              <option value="saved">{t("ذخیره‌ها")}</option>
              <option value="liked">{t("لایک‌ها")}</option>
              <option value="all">{t("همه")}</option>
            </select>
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px' }}>
            <span style={{ color: 'var(--text-secondary)' }}>{t("مجموعه")}:</span>
            <select className="filter-select" value={downloadCollection} onChange={e => setDownloadCollection(e.target.value)}>
              <option value="">{t("همهٔ مجموعه‌ها")}</option>
              {collections.map(item => <option key={item.name} value={item.name}>{item.name} ({item.count})</option>)}
            </select>
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer', fontWeight: 600 }}><input type="checkbox" checked={continuousDownload} onChange={e => setContinuousDownload(e.target.checked)} style={{ accentColor: 'var(--primary)', width: '16px', height: '16px' }} />{t("دانلود پیوسته (نامحدود تا پایان)")}</label>
          {!continuousDownload && <label>{t("تعداد هر اجرا")}<input className="meta-input" type="number" min="1" max="10000" style={{ width: '80px' }} value={downloadBatch} onChange={e => setDownloadBatch(Math.max(1, Number(e.target.value) || 1))} /></label>}
        </div>
        <p>{effectiveDownloader === 'public' ? t("روش عمومی از gallery-dl برای عکس و چنداسلایدی و yt-dlp برای ویدیو استفاده می‌کند؛ کوکی یا نشست شما را نمی‌خواند و پست خصوصی را نمی‌تواند بگیرد.") : t("روش نشست از حساب واردشده استفاده می‌کند و برای ذخیره‌های خصوصی مناسب است؛ هشدار محدودیت، کار را متوقف می‌کند.")}</p>
        {!publicDownloaderAvailable && <p role="status">{t('در این نسخه، دانلود عمومی به‌دلیل نبود وابستگی‌های آن غیرفعال است.')}</p>}
        <p style={{ color: 'var(--text-secondary)', marginBottom: 0 }}>
          {t('History:')} {t(checkpoint?.historical_complete ? 'complete' : checkpoint?.historical_scan_cursor ? 'more pages available' : 'not started')}.
          {checkpoint?.recent_scan_cursor ? ` ${t('Recent scan has more pages; run Sync new saves again.')}` : ''}
          {latestSync ? ` ${t('Last sync:')} ${new Date(latestSync.started_at * 1000).toLocaleString(language === 'fa' ? 'fa-IR' : 'en-US')}, ${t(latestSync.mode)}, ${t(latestSync.outcome)}, ${latestSync.pages} ${t('pages')}, ${latestSync.discovered} ${t('new')}, ${latestSync.duplicates} ${t('known')}, ${latestSync.downloaded} ${t('downloaded')}, ${latestSync.download_failed} ${t('download errors')}.` : ''}
        </p>
      </div>
      <div style={{ display: 'flex', gap: '10px', marginBottom: '20px' }}>
        {!!stats.DOWNLOAD_FAILED && <button className="btn" onClick={() => retryFailures('download')}>{t("آماده‌سازی دوبارهٔ دانلودها")}</button>}
        {!!stats.ANALYSIS_FAILED && <button className="btn" onClick={() => retryFailures('analysis')}>{t("تلاش دوبارهٔ AI")}</button>}
      </div>

      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-title">{t("کل پست‌ها")}</div>
          <div className="stat-value">{stats.TOTAL || 0}</div>
        </div>
        <div className="stat-card">
          <div className="stat-title">{t("دانلودشده")}</div>
          <div className="stat-value">{(stats.DOWNLOAD_OK || 0) + (stats.ANALYSIS_PENDING || 0) + (stats.ANALYSIS_OK || 0) + (stats.REVIEW_REQUIRED || 0) + (stats.APPROVED || 0) + (stats.ORGANIZED || 0)}</div>
        </div>
        <div className="stat-card">
          <div className="stat-title">{t("در انتظار دانلود")}</div>
          <div className="stat-value">{(stats.DISCOVERED || 0) + (stats.DOWNLOAD_PENDING || 0)}</div>
        </div>
        <div className="stat-card">
          <div className="stat-title">{t("تحلیل‌شده با AI")}</div>
          <div className="stat-value">{(stats.ANALYSIS_OK || 0) + (stats.APPROVED || 0) + (stats.ORGANIZED || 0)}</div>
        </div>
      </div>
      <details style={{ margin: '4px 0 20px' }}>
      <summary style={{ cursor: 'pointer', color: 'var(--text-secondary)' }}>{t('آمار بیشتر')}</summary>
      <div className="stats-grid" style={{ marginTop: '12px' }}>
        <div className="stat-card">
          <div className="stat-title">{t("دانلود ناموفق")}</div>
          <div className="stat-value" style={{ color: 'var(--error)' }}>{stats.DOWNLOAD_FAILED || 0}</div>
        </div>
        <div className="stat-card">
          <div className="stat-title">{t("دسته‌بندی‌شده")}</div>
          <div className="stat-value" style={{ color: 'var(--success)' }}>{stats.ORGANIZED || 0}</div>
        </div>
        <div className="stat-card"><div className="stat-title">{t("نیازمند بازبینی AI")}</div><div className="stat-value">{stats.REVIEW_REQUIRED || 0}</div></div>
        <div className="stat-card"><div className="stat-title">{t("خطاهای AI")}</div><div className="stat-value">{stats.ANALYSIS_FAILED || 0}</div></div>
        <div className="stat-card"><div className="stat-title">{t("ناموجود در اینترنت")}</div><div className="stat-value">{stats.UNAVAILABLE || 0}</div></div>
        <div className="stat-card"><div className="stat-title">{t("فایل محلی گم‌شده")}</div><div className="stat-value">{stats.MISSING_LOCAL || 0}</div></div>
      </div>
      </details>

      <h2 style={{ fontSize: '18px', marginBottom: '15px' }}>{t("کارهای در حال اجرا")}</h2>
      {activeJobs.length === 0 ? (
        <p style={{ color: 'var(--text-secondary)' }}>{t("کاری در حال اجرا نیست.")}</p>
      ) : (
        activeJobs.map(job => (
          <div key={job.id} className="job-card">
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '10px' }}>
              <strong>{t(job.type)} - {t(job.status)}</strong>
              <button className="btn btn-danger" style={{ padding: '4px 10px' }} onClick={() => cancelJob(job.id)}>
                <Square size={14} /> {t("توقف")}</button>
            </div>
            <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>{job.message ? translateProgress(job.message, language) : t('Processing...')}</div>
            <div className="progress-bar-container">
              <div className="progress-bar-fill" style={{ width: `${job.progress || 0}%` }}></div>
            </div>
          </div>
        ))
      )}
    </div>
  );
};

export default Dashboard;
