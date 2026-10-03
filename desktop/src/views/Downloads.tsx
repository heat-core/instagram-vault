import { useI18n, translateProgress } from '../i18n';
import { useState, useEffect } from 'react';
import { DownloadCloud, Activity, CheckCircle2, Trash2, StopCircle, ChevronDown, ChevronUp, Search, Video, Image, AlertOctagon, RefreshCw, Play, ArrowDownWideNarrow, ArrowUpNarrowWide } from 'lucide-react';
import MediaCard from '../components/MediaCard';
import type { Post } from '../components/MediaCard';
import Inspector from '../components/Inspector';

const API_BASE = 'http://127.0.0.1:8000';

type FilterType = 'all' | 'video' | 'photo' | 'failed';

const Downloads = () => {
  const { t, language } = useI18n();
  const [downloadJobs, setDownloadJobs] = useState<any[]>([]);
  const [recentDownloads, setRecentDownloads] = useState<Post[]>([]);
  const [selectedPost, setSelectedPost] = useState<Post | null>(null);
  const [jobItems, setJobItems] = useState<{ post_pk: string; stage: string }[]>([]);
  const [showAllItems, setShowAllItems] = useState(false);
  const [dailyRemaining, setDailyRemaining] = useState<number | null>(null);
  const [dailyReset, setDailyReset] = useState<number | null>(null);
  const [filter, setFilter] = useState<FilterType>('all');
  const [search, setSearch] = useState('');
  const [sortBy, setSortBy] = useState('status_updated_at');
  const [sortOrder, setSortOrder] = useState<'desc' | 'asc'>('desc');
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [counts, setCounts] = useState<{ all: number; video: number; photo: number; failed: number }>({
    all: 0, video: 0, photo: 0, failed: 0
  });
  const [actionToast, setActionToast] = useState('');
  const [isJobsSectionOpen, setIsJobsSectionOpen] = useState(() => {
    return localStorage.getItem('downloads_jobs_collapsed') !== 'true';
  });

  const toggleJobsSection = () => {
    setIsJobsSectionOpen(prev => {
      const next = !prev;
      localStorage.setItem('downloads_jobs_collapsed', String(!next));
      return next;
    });
  };

  const fetchJobsAndStats = async () => {
    try {
      const statsRes = await fetch(`${API_BASE}/stats`);
      if (statsRes.ok) {
        const stats = await statsRes.json();
        setDailyRemaining(stats.DOWNLOAD_DAILY_REMAINING ?? null);
        setDailyReset(stats.DOWNLOAD_DAILY_RESET_AT ?? null);
        setCounts({
          all: (stats.DOWNLOAD_OK || 0) + (stats.ANALYSIS_OK || 0) + (stats.ANALYSIS_PENDING || 0) + (stats.APPROVED || 0),
          video: stats.TOTAL_VIDEOS || 0,
          photo: stats.TOTAL_PHOTOS || 0,
          failed: stats.DOWNLOAD_FAILED || 0
        });
      }
      const jobsRes = await fetch(`${API_BASE}/jobs`);
      if (jobsRes.ok) {
        const jobsData = await jobsRes.json();
        const visibleJobs = jobsData.filter((j: any) => j.type === 'download').slice(0, 5);
        setDownloadJobs(visibleJobs);
        const active = visibleJobs.find((j: any) => j.status === 'RUNNING');
        if (active) {
          const itemRes = await fetch(`${API_BASE}/jobs/${active.id}/items`);
          if (itemRes.ok) setJobItems(await itemRes.json());
        } else {
          setJobItems([]);
        }
      }
    } catch (e) {
      console.error("Failed to fetch jobs or stats", e);
    }
  };

  const fetchDownloads = async (offset = 0) => {
    try {
      const params = new URLSearchParams({ limit: '60', offset: String(offset) });
      if (filter === 'failed') {
        params.set('status', 'DOWNLOAD_FAILED');
      } else {
        params.set('status', 'downloaded');
        if (filter === 'video') params.set('media_type', '2');
        if (filter === 'photo') params.set('media_type', '1');
      }
      if (search.trim()) {
        params.set('search', search.trim());
      }
      if (sortBy) {
        params.set('sort_by', sortBy);
      }
      if (sortOrder) {
        params.set('sort_order', sortOrder);
      }

      const res = await fetch(`${API_BASE}/posts?${params.toString()}`);
      if (res.ok) {
        const data = await res.json();
        if (offset === 0) {
          setRecentDownloads(data);
        } else {
          setRecentDownloads(prev => [...prev, ...data]);
        }
        setHasMore(data.length === 60);
      }
    } catch (e) {
      console.error("Failed to fetch recent downloads", e);
    }
  };

  useEffect(() => {
    fetchJobsAndStats();
    const interval = setInterval(fetchJobsAndStats, 3000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    fetchDownloads(0);
  }, [filter, search, sortBy, sortOrder]);

  const loadMore = async () => {
    if (loadingMore || !hasMore) return;
    setLoadingMore(true);
    await fetchDownloads(recentDownloads.length);
    setLoadingMore(false);
  };

  const cancelJob = async (jobId: string) => {
    try {
      await fetch(`${API_BASE}/jobs/${jobId}/cancel`, { method: 'POST' });
      fetchJobsAndStats();
    } catch (e) {
      console.error("Failed to cancel job", e);
    }
  };

  const cleanupJobs = async () => {
    try {
      await fetch(`${API_BASE}/jobs/cleanup`, { method: 'POST' });
      fetchJobsAndStats();
    } catch (e) {
      console.error("Failed to cleanup jobs", e);
    }
  };

  const retryFailedPosts = async () => {
    try {
      const res = await fetch(`${API_BASE}/posts/retry-failed`, { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        setActionToast(data.message || t('پست‌ها برای دانلود مجدد آماده شدند.'));
        setTimeout(() => setActionToast(''), 4000);
        fetchJobsAndStats();
        fetchDownloads(0);
      }
    } catch (e) {
      console.error("Failed to retry posts", e);
    }
  };

  const startContinuousDownload = async () => {
    try {
      const res = await fetch(`${API_BASE}/jobs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          job_type: 'download',
          params: {
            batch_size: 0,
            continuous: true,
            source: 'all',
            downloader: localStorage.getItem('downloadMethod') || 'session',
            quality_target: localStorage.getItem('qualityTarget') || 'high'
          }
        })
      });
      if (res.ok) {
        setActionToast(t('دانلود پیوسته تمام موارد آغاز شد.'));
        setTimeout(() => setActionToast(''), 4000);
        fetchJobsAndStats();
      }
    } catch (e) {
      console.error("Failed to start continuous download", e);
    }
  };

  const handleSaveMetadata = async (pk: string, data: any) => {
    try {
      const res = await fetch(`${API_BASE}/posts/${pk}/metadata`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      });
      if (!res.ok) throw new Error((await res.json()).detail || 'Save failed');
      fetchDownloads(0);
      if (selectedPost && selectedPost.pk === pk) {
        setSelectedPost({ ...selectedPost, ai_category: data.category, ai_tags: data.tags, ai_summary: data.summary, status: data.status || selectedPost.status });
      }
    } catch (e) {
      console.error("Failed to save metadata", e);
    }
  };

  const activeJobs = downloadJobs.filter(j => j.status === 'RUNNING' || j.status === 'QUEUED');
  const pastJobs = downloadJobs.filter(j => j.status !== 'RUNNING' && j.status !== 'QUEUED');

  return (
    <div className="view-container animate-fade-in" style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '24px' }}>
      <div>
        <h1 className="view-title" style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <DownloadCloud size={26} color="var(--primary)" /> {t("روند و فایل‌های دانلود")}
        </h1>
        <p style={{ color: 'var(--text-secondary)' }}>
          {t("مدیریت فرآیند دریافت، فایل‌های ذخیره‌شده روی سیستم و رهگیری پست‌های نیازمند بررسی.")}
        </p>
        {dailyRemaining === 0 && (
          <div className="card" role="status" style={{ marginTop: '12px', display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: '10px' }}>
            <span>{t('سقف داخلی دانلود در ۲۴ ساعت اخیر تکمیل شده است؛ هر تلاش ناموفق هم شمرده می‌شود. موارد در صف می‌مانند و بعد از زمان زیر دوباره امکان تلاش هست:')} {dailyReset ? new Date(dailyReset * 1000).toLocaleString(language === 'fa' ? 'fa-IR' : 'en-US') : '—'}</span>
            <button className="btn btn-primary" onClick={async () => {
              await fetch(`${API_BASE}/settings/reset-limit`, { method: 'POST' });
              fetchJobsAndStats();
            }}>{t("رفع محدودیت و ادامه دانلود")}</button>
          </div>
        )}
      </div>

      {/* Download Jobs Section */}
      <div className="card" style={{ padding: '18px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: isJobsSectionOpen ? '14px' : '0', flexWrap: 'wrap', gap: '8px' }}>
          <div
            onClick={toggleJobsSection}
            style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', userSelect: 'none' }}
            title={isJobsSectionOpen ? t("بستن فهرست کارهای دانلود") : t("باز کردن فهرست کارهای دانلود")}
          >
            <h2 style={{ fontSize: '16px', display: 'flex', alignItems: 'center', gap: '8px', margin: 0 }}>
              <Activity size={18} color="var(--primary)" /> {t("کارهای دانلود")}
              {activeJobs.length > 0 && (
                <span className="badge" style={{ background: 'rgba(59, 130, 246, 0.2)', color: '#3b82f6' }}>
                  {activeJobs.length} {t('در حال اجرا')}
                </span>
              )}
            </h2>
            <button
              type="button"
              className="btn btn-sm"
              style={{ padding: '2px 6px', border: 'none', background: 'transparent', color: 'var(--text-secondary)' }}
              aria-label={isJobsSectionOpen ? t("بستن") : t("باز کردن")}
            >
              {isJobsSectionOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
            </button>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            {activeJobs.length === 0 && isJobsSectionOpen && (
              <button
                className="btn btn-primary btn-sm"
                onClick={startContinuousDownload}
                style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', padding: '6px 14px' }}
              >
                <Play size={14} /> {t("شروع دانلود پیوسته")}
              </button>
            )}
            {pastJobs.length > 0 && isJobsSectionOpen && (
              <button
                className="btn btn-sm"
                onClick={cleanupJobs}
                style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', padding: '6px 12px' }}
                title={t("پاک‌کردن تاریخچه کارهای پایان‌یافته برای خلوت‌شدن صفحه")}
              >
                <Trash2 size={14} /> {t("پاک‌سازی کارهای پایان‌یافته")}
              </button>
            )}
            <button
              type="button"
              className="btn btn-sm"
              onClick={toggleJobsSection}
              style={{ fontSize: '12px', padding: '4px 10px', display: 'flex', alignItems: 'center', gap: '4px' }}
            >
              {isJobsSectionOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
              {isJobsSectionOpen ? t("بستن بخش کارهای دانلود") : t("نمایش کارهای دانلود")}
            </button>
          </div>
        </div>

        {isJobsSectionOpen && (
          <>
            {downloadJobs.length === 0 ? (
          <div style={{ padding: '24px', textAlign: 'center', color: 'var(--text-secondary)', fontSize: '14px', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '12px' }}>
            <span>{t('هیچ کار دانلودی در حال حاضر فعال نیست.')}</span>
            <button className="btn btn-primary" onClick={startContinuousDownload} style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Play size={16} /> {t("شروع دانلود پیوسته همه فایل‌ها")}
            </button>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {downloadJobs.map(job => (
              <div key={job.id} style={{ background: 'var(--bg-main)', padding: '14px', borderRadius: '8px', border: '1px solid var(--border)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span style={{ fontWeight: 600 }}>{t('دانلود پست‌ها')}</span>
                    <span className="badge" style={{ fontSize: '11px' }}>{t(job.status)}</span>
                  </div>
                  {(job.status === 'RUNNING' || job.status === 'QUEUED') && (
                    <button
                      className="btn btn-sm"
                      onClick={() => cancelJob(job.id)}
                      style={{ color: 'var(--error)', display: 'flex', alignItems: 'center', gap: '4px', padding: '4px 8px' }}
                    >
                      <StopCircle size={14} /> {t('لغو کار')}
                    </button>
                  )}
                </div>

                <div className="progress-bar-bg" style={{ height: '7px', background: 'var(--bg-card)', borderRadius: '4px', overflow: 'hidden' }}>
                  <div className="progress-bar-fill" style={{ height: '100%', width: `${job.progress}%`, background: 'var(--primary)', transition: 'width 0.3s ease' }}></div>
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '6px', fontSize: '12px', color: 'var(--text-secondary)' }}>
                  <span>{job.message ? translateProgress(job.message, language) : t('Processing...')}</span>
                  <span>{Math.round(job.progress)}%</span>
                </div>

                {job.status === 'RUNNING' && jobItems.length > 0 && (
                  <div style={{ marginTop: '10px', borderTop: '1px solid var(--border)', paddingTop: '8px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                        {t('آخرین مورد:')} <code dir="ltr">{jobItems[0].post_pk}</code> ({translateProgress(jobItems[0].stage, language)})
                      </span>
                      {jobItems.length > 1 && (
                        <button
                          type="button"
                          className="btn btn-sm"
                          style={{ fontSize: '11px', padding: '2px 8px' }}
                          onClick={() => setShowAllItems(!showAllItems)}
                        >
                          {showAllItems ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                          {showAllItems ? t('بستن جزئیات') : `${t('مشاهده همه')} (${jobItems.length})`}
                        </button>
                      )}
                    </div>
                    {showAllItems && (
                      <div style={{ maxHeight: '180px', overflowY: 'auto', marginTop: '8px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                        {jobItems.map(item => (
                          <div key={item.post_pk} dir="ltr" style={{ fontSize: '11px', padding: '4px 8px', background: 'var(--bg-card)', borderRadius: '4px', display: 'flex', justifyContent: 'space-between' }}>
                            <span>{item.post_pk}</span>
                            <span style={{ color: 'var(--text-secondary)' }}>{translateProgress(item.stage, language)}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
          </>
        )}
      </div>

      {/* Recent Downloads & Media Grid Section */}
      <div className="card" style={{ flex: 1, display: 'flex', flexDirection: 'column', padding: '20px', gap: '16px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
          <h2 style={{ fontSize: '16px', display: 'flex', alignItems: 'center', gap: '8px', margin: 0 }}>
            <CheckCircle2 size={18} color="var(--success)" /> {t("رسانه‌های دانلودشده")}
            <span style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
              ({recentDownloads.length} {t('مورد نمایش‌داده‌شده')})
            </span>
          </h2>

          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
            {/* Sorting Controls */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
              <select
                className="filter-select"
                value={sortBy}
                onChange={e => setSortBy(e.target.value)}
                style={{ fontSize: '13px', padding: '6px 8px' }}
                title={t("مرتب‌سازی بر اساس")}
              >
                <option value="status_updated_at">{t("تاریخ دانلود / ثبت")}</option>
                <option value="activity_date">{t("تاریخ فعالیت (هوشمند)")}</option>
                <option value="saved_at">{t("تاریخ ذخیره در اینستاگرام")}</option>
                <option value="liked_at">{t("تاریخ لایک در اینستاگرام")}</option>
                <option value="taken_at">{t("تاریخ انتشار اصلی پست")}</option>
              </select>
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => setSortOrder(prev => prev === 'desc' ? 'asc' : 'desc')}
                title={sortOrder === 'desc' ? t("جدیدترین به قدیمی‌ترین (نزولی)") : t("قدیمی‌ترین به جدیدترین (صعودی)")}
              >
                {sortOrder === 'desc' ? <ArrowDownWideNarrow size={14} /> : <ArrowUpNarrowWide size={14} />}
              </button>
            </div>

            <div style={{ position: 'relative', minWidth: '180px' }}>
              <input
                type="text"
                className="meta-input"
                placeholder={t("جستجو...")}
                value={search}
                onChange={e => setSearch(e.target.value)}
                style={{ padding: '6px 10px', fontSize: '13px', width: '100%' }}
              />
              <Search size={14} style={{ position: 'absolute', left: language === 'fa' ? undefined : '8px', right: language === 'fa' ? '8px' : undefined, top: '9px', color: 'var(--text-secondary)' }} />
            </div>
            <button className="btn btn-sm" onClick={() => fetchDownloads(0)} title={t("تازه‌سازی")}>
              <RefreshCw size={14} />
            </button>
          </div>
        </div>

        {/* Filter Tabs */}
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', borderBottom: '1px solid var(--border)', paddingBottom: '12px' }}>
          <button
            className={`btn btn-sm ${filter === 'all' ? 'btn-primary' : ''}`}
            onClick={() => setFilter('all')}
            style={{ display: 'flex', alignItems: 'center', gap: '6px' }}
          >
            {t("همه دریافت‌شده‌ها")} {counts.all > 0 && <span className="badge">{counts.all}</span>}
          </button>
          <button
            className={`btn btn-sm ${filter === 'video' ? 'btn-primary' : ''}`}
            onClick={() => setFilter('video')}
            style={{ display: 'flex', alignItems: 'center', gap: '6px' }}
          >
            <Video size={14} /> {t("ریلزها و ویدیوها")}
          </button>
          <button
            className={`btn btn-sm ${filter === 'photo' ? 'btn-primary' : ''}`}
            onClick={() => setFilter('photo')}
            style={{ display: 'flex', alignItems: 'center', gap: '6px' }}
          >
            <Image size={14} /> {t("عکس‌ها")}
          </button>
          <button
            className={`btn btn-sm ${filter === 'failed' ? 'btn-primary' : ''}`}
            onClick={() => setFilter('failed')}
            style={{ display: 'flex', alignItems: 'center', gap: '6px', color: filter === 'failed' ? '#fff' : 'var(--error)' }}
          >
            <AlertOctagon size={14} /> {t("ناموفق‌ها / نیازمند لاگین")} {counts.failed > 0 && <span className="badge" style={{ background: 'var(--error)' }}>{counts.failed}</span>}
          </button>
        </div>

        {actionToast && (
          <div className="card" role="status" style={{ padding: '10px 16px', color: 'var(--success)', borderColor: 'var(--success)' }}>
            {actionToast}
          </div>
        )}

        {filter === 'failed' && (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px', background: 'rgba(239, 68, 68, 0.08)', padding: '12px 16px', borderRadius: '8px', border: '1px solid rgba(239, 68, 68, 0.2)' }}>
            <span style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
              {t("این پست‌ها به دلیل نیاز به سشن لاگین یا محدودیت موقت اینستاگرام متوقف شده‌اند. مشخصات و لینک‌ها در دیتابیس محفوظ است.")}
            </span>
            <button
              className="btn btn-sm btn-primary"
              onClick={retryFailedPosts}
              style={{ display: 'flex', alignItems: 'center', gap: '6px', whiteSpace: 'nowrap' }}
            >
              <RefreshCw size={14} />
              {t("انتقال مجدد به صف دانلود (Retry All)")}
            </button>
          </div>
        )}

        {/* Media Grid */}
        <div className="media-grid">
          {recentDownloads.map(post => (
            <MediaCard 
              key={post.pk} 
              post={post} 
              onClick={(p) => setSelectedPost(p)} 
            />
          ))}
          {recentDownloads.length === 0 && (
            <div style={{ gridColumn: '1 / -1', padding: '40px', textAlign: 'center', color: 'var(--text-secondary)' }}>
              {filter === 'failed'
                ? t('هیچ پست ناموفقی ثبت نشده است.')
                : t('هیچ رسانهٔ دانلودشده‌ای مطابق فیلتر یافت نشد.')}
            </div>
          )}
        </div>

        {hasMore && (
          <div style={{ display: 'flex', justifyContent: 'center', marginTop: '16px' }}>
            <button className="btn" disabled={loadingMore} onClick={loadMore}>
              {loadingMore ? t("در حال دریافت...") : t("نمایش موارد بیشتر")}
            </button>
          </div>
        )}
      </div>

      <Inspector 
        post={selectedPost} 
        isOpen={!!selectedPost} 
        onClose={() => setSelectedPost(null)}
        onSave={handleSaveMetadata}
      />
    </div>
  );
};

export default Downloads;
