import { useI18n } from '../i18n';
import { useState, useEffect, useRef } from 'react';
import { Bot, Check, CheckCheck, ChevronLeft, ChevronRight, LayoutGrid, LayoutList, Sparkles, X } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import type { Post } from '../components/MediaCard';

const API_BASE = 'http://127.0.0.1:8000';

type ReviewTab = 'ANALYSIS_OK' | 'REVIEW_REQUIRED' | 'APPROVED';

const AIReview = () => {
  const { t, language } = useI18n();
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<ReviewTab>('ANALYSIS_OK');
  const [viewMode, setViewMode] = useState<'single' | 'grid'>('single');
  const [posts, setPosts] = useState<Post[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [pageOffset, setPageOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [error, setError] = useState('');
  const [actionSuccess, setActionSuccess] = useState('');
  const [unclassifiedCount, setUnclassifiedCount] = useState<number>(0);
  const [isStartingAnalysis, setIsStartingAnalysis] = useState(false);
  const requestId = useRef(0);

  const [formData, setFormData] = useState({
    category: '',
    tags: '',
    summary: ''
  });

  const fetchStats = async () => {
    try {
      const res = await fetch(`${API_BASE}/stats`);
      if (res.ok) {
        const stats = await res.json();
        setUnclassifiedCount(stats.DOWNLOAD_OK || 0);
      }
    } catch {
      // ignore
    }
  };

  const fetchPosts = async (offset = 0) => {
    const thisRequest = ++requestId.current;
    try {
      const params = new URLSearchParams({
        status: activeTab,
        limit: '50',
        offset: String(offset)
      });
      const res = await fetch(`${API_BASE}/posts?${params.toString()}`);
      if (!res.ok) throw new Error('Could not load classified posts');
      const data = await res.json();
      if (thisRequest !== requestId.current) return;
      setPosts(data);
      setPageOffset(offset);
      setCurrentIndex(0);
      setHasMore(data.length === 50);
      setError('');
    } catch (e) {
      setError(String(e));
    }
  };

  useEffect(() => {
    fetchStats();
    void fetchPosts(0);
  }, [activeTab]);

  const currentPost = posts[currentIndex];

  useEffect(() => {
    if (currentPost) {
      setFormData({
        category: currentPost.ai_category || '',
        tags: currentPost.ai_tags || '',
        summary: currentPost.ai_summary || ''
      });
    }
  }, [currentPost]);

  const nextPost = () => {
    if (currentIndex < posts.length - 1) {
      setCurrentIndex(currentIndex + 1);
    } else if (hasMore) {
      void fetchPosts(pageOffset + posts.length);
    }
  };

  const prevPost = () => {
    if (currentIndex > 0) {
      setCurrentIndex(currentIndex - 1);
    }
  };

  const handleSaveAndApprove = async () => {
    if (!currentPost) return;
    try {
      const res = await fetch(`${API_BASE}/posts/${currentPost.pk}/metadata`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          category: formData.category,
          tags: formData.tags,
          summary: formData.summary,
          status: 'APPROVED'
        })
      });
      if (!res.ok) throw new Error('Could not save metadata');
      setActionSuccess(t('پست با موفقیت تأیید و ذخیره شد.'));
      setTimeout(() => setActionSuccess(''), 2500);

      // Remove from current list if we are in ANALYSIS_OK or REVIEW_REQUIRED
      if (activeTab !== 'APPROVED') {
        const remaining = posts.filter((_, idx) => idx !== currentIndex);
        setPosts(remaining);
        if (currentIndex >= remaining.length && remaining.length > 0) {
          setCurrentIndex(remaining.length - 1);
        }
      } else {
        nextPost();
      }
    } catch (e) {
      setError(String(e));
    }
  };

  const handleBulkApprove = async () => {
    if (posts.length === 0) return;
    const confirmMsg = language === 'fa' 
      ? `آیا از تأیید همگانی تمام ${posts.length} مورد این صفحه مطمئن هستید؟` 
      : `Are you sure you want to approve all ${posts.length} items on this page?`;
    if (!confirm(confirmMsg)) return;
    try {
      for (const p of posts) {
        await fetch(`${API_BASE}/posts/${p.pk}/metadata`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ status: 'APPROVED' })
        });
      }
      setActionSuccess(t('تمام موارد با موفقیت تأیید شدند.'));
      setTimeout(() => setActionSuccess(''), 2500);
      void fetchPosts(0);
    } catch (e) {
      setError(String(e));
    }
  };

  const startAnalysisJob = async () => {
    setIsStartingAnalysis(true);
    try {
      const res = await fetch(`${API_BASE}/jobs/analysis`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ limit: 0, continuous: true })
      });
      if (res.ok) {
        setActionSuccess(t('کار تحلیل هوش مصنوعی آغاز شد. پیشرفت در تب دانلودها و داشبورد قابل مشاهده است.'));
        setTimeout(() => setActionSuccess(''), 4000);
        setTimeout(() => fetchPosts(0), 2000);
      } else {
        throw new Error('Could not start analysis job');
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setIsStartingAnalysis(false);
    }
  };

  return (
    <div className="view-container animate-fade-in" style={{ padding: '20px', display: 'flex', flexDirection: 'column', height: '100%', gap: '16px' }}>
      {/* Top Header */}
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
          <div>
            <h1 className="view-title" style={{ display: 'flex', alignItems: 'center', gap: '10px', margin: 0 }}>
              <Bot size={26} color="var(--primary)" /> {t("بازبینی هوش مصنوعی")}
            </h1>
            <p style={{ color: 'var(--text-secondary)', marginTop: '4px' }}>
              {t("بررسی تحلیل‌ها، دسته‌بندی‌ها و تگ‌های تولیدشده توسط هوش مصنوعی و نهایی‌سازی آرشیو.")}
            </p>
          </div>

          {/* Quick Actions */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
            {unclassifiedCount > 0 && (
              <button
                className="btn btn-primary"
                onClick={startAnalysisJob}
                disabled={isStartingAnalysis}
                style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px' }}
              >
                <Sparkles size={15} />
                {isStartingAnalysis ? t('در حال شروع...') : `${t('شروع تحلیل AI')} (${unclassifiedCount} ${t('دانلودشده')})`}
              </button>
            )}

            {posts.length > 0 && activeTab !== 'APPROVED' && (
              <button
                className="btn"
                onClick={handleBulkApprove}
                style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px' }}
                title={t("تأیید دسته‌ای همه موارد این صفحه")}
              >
                <CheckCheck size={15} color="var(--success)" />
                {t("تأیید همگانی این صفحه")}
              </button>
            )}

            {/* View Mode Toggle */}
            <div style={{ display: 'flex', background: 'var(--bg-card)', padding: '2px', borderRadius: '6px', border: '1px solid var(--border)' }}>
              <button
                className="btn btn-sm"
                onClick={() => setViewMode('single')}
                style={{
                  background: viewMode === 'single' ? 'var(--primary)' : 'transparent',
                  color: viewMode === 'single' ? '#fff' : 'var(--text-secondary)',
                  padding: '4px 8px'
                }}
                title={t("نمای تکی / ویرایشگر")}
              >
                <LayoutList size={14} />
              </button>
              <button
                className="btn btn-sm"
                onClick={() => setViewMode('grid')}
                style={{
                  background: viewMode === 'grid' ? 'var(--primary)' : 'transparent',
                  color: viewMode === 'grid' ? '#fff' : 'var(--text-secondary)',
                  padding: '4px 8px'
                }}
                title={t("نمای شبکه‌ای")}
              >
                <LayoutGrid size={14} />
              </button>
            </div>
          </div>
        </div>

        {/* Tab Filters */}
        <div style={{ display: 'flex', gap: '10px', marginTop: '14px', borderBottom: '1px solid var(--border)', paddingBottom: '10px', flexWrap: 'wrap' }}>
          <button
            className={`btn btn-sm ${activeTab === 'ANALYSIS_OK' ? 'btn-primary' : ''}`}
            onClick={() => setActiveTab('ANALYSIS_OK')}
            style={{ display: 'flex', alignItems: 'center', gap: '6px' }}
          >
            <Sparkles size={14} />
            {t("تحلیل‌شده‌ها با هوش مصنوعی")}
            {activeTab === 'ANALYSIS_OK' && posts.length > 0 && <span className="badge">{posts.length}</span>}
          </button>

          <button
            className={`btn btn-sm ${activeTab === 'REVIEW_REQUIRED' ? 'btn-primary' : ''}`}
            onClick={() => setActiveTab('REVIEW_REQUIRED')}
            style={{ display: 'flex', alignItems: 'center', gap: '6px' }}
          >
            {t("نیازمند بازبینی دستی")}
            {activeTab === 'REVIEW_REQUIRED' && posts.length > 0 && <span className="badge">{posts.length}</span>}
          </button>

          <button
            className={`btn btn-sm ${activeTab === 'APPROVED' ? 'btn-primary' : ''}`}
            onClick={() => setActiveTab('APPROVED')}
            style={{ display: 'flex', alignItems: 'center', gap: '6px' }}
          >
            <Check size={14} />
            {t("تأییدشده‌های نهایی")}
            {activeTab === 'APPROVED' && posts.length > 0 && <span className="badge">{posts.length}</span>}
          </button>
        </div>

        {error && <div className="card" role="alert" style={{ marginTop: '10px', color: 'var(--error)', borderColor: 'var(--error)' }}>{error}</div>}
        {actionSuccess && <div className="card" role="status" style={{ marginTop: '10px', color: 'var(--success)', borderColor: 'var(--success)' }}>{actionSuccess}</div>}
      </div>

      {/* Main Content Area */}
      {posts.length === 0 ? (
        <div className="card" style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '16px', color: 'var(--text-secondary)', padding: '60px 20px', textAlign: 'center' }}>
          <Bot size={48} color="var(--text-secondary)" style={{ opacity: 0.5 }} />
          <div>
            <div style={{ fontSize: '16px', fontWeight: 600, color: 'var(--text-main)', marginBottom: '6px' }}>
              {activeTab === 'ANALYSIS_OK' && t('هیچ پستی در وضعیت تحلیل‌شده یافت نشد.')}
              {activeTab === 'REVIEW_REQUIRED' && t('هیچ پست نامطمئنی برای بازبینی دستی وجود ندارد.')}
              {activeTab === 'APPROVED' && t('هنوز پستی در این بخش تأیید نشده است.')}
            </div>
            {unclassifiedCount > 0 && (
              <div style={{ fontSize: '13px', marginTop: '6px' }}>
                {unclassifiedCount} {t('پست دانلودشده آماده تحلیل با هوش مصنوعی هستند.')}
              </div>
            )}
          </div>
          {unclassifiedCount > 0 && (
            <button className="btn btn-primary" onClick={startAnalysisJob} disabled={isStartingAnalysis}>
              <Sparkles size={16} /> {t("شروع تحلیل هوش مصنوعی برای دانلودها")}
            </button>
          )}
        </div>
      ) : viewMode === 'grid' ? (
        /* Grid Overview Mode */
        <div style={{ flex: 1, overflowY: 'auto' }}>
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
            gap: '16px',
            paddingBottom: '20px'
          }}>
            {posts.map((post, idx) => (
              <div
                key={post.pk}
                className="card"
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  overflow: 'hidden',
                  padding: 0,
                  cursor: 'pointer',
                  border: currentIndex === idx ? '2px solid var(--primary)' : '1px solid var(--border)'
                }}
                onClick={() => {
                  setCurrentIndex(idx);
                  setViewMode('single');
                }}
              >
                <div style={{ width: '100%', height: '160px', background: '#000', position: 'relative' }}>
                  {post.thumbnail && /\.(mp4|mov)$/i.test(post.thumbnail) ? (
                    <video src={`${API_BASE}${post.thumbnail}`} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                  ) : post.thumbnail ? (
                    <img src={`${API_BASE}${post.thumbnail}`} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                  ) : (
                    <div style={{ width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#666' }}>{t("رسانه‌ای موجود نیست")}</div>
                  )}
                  {post.ai_confidence && (
                    <span className="badge" style={{ position: 'absolute', top: '8px', right: '8px', background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)', color: '#fff' }}>
                      {Math.round(Number(post.ai_confidence) * 100)}%
                    </span>
                  )}
                </div>
                <div style={{ padding: '12px', display: 'flex', flexDirection: 'column', gap: '6px', flex: 1 }}>
                  <div style={{ fontWeight: 600, fontSize: '13px', color: 'var(--primary)' }}>
                    {post.ai_category || t('دسته‌بندی‌نشده')}
                  </div>
                  <div style={{ fontSize: '12px', color: 'var(--text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>
                    {post.ai_summary || post.caption || '—'}
                  </div>
                  <div style={{ marginTop: 'auto', paddingTop: '8px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '11px', color: 'var(--text-secondary)' }}>
                    <span>@{post.owner_username}</span>
                    <button
                      className="btn btn-sm"
                      style={{ padding: '3px 8px', fontSize: '11px' }}
                      onClick={(e) => {
                        e.stopPropagation();
                        setCurrentIndex(idx);
                        setViewMode('single');
                      }}
                    >
                      {t("ویرایش")}
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : (
        /* Single Item Editor Mode */
        <div style={{ flex: 1, display: 'flex', gap: '20px', overflow: 'hidden' }}>
          {/* Left: Media Viewer */}
          <div className="card" style={{ flex: 1, display: 'flex', flexDirection: 'column', background: '#000', overflow: 'hidden', padding: 0, position: 'relative' }}>
            {currentPost?.thumbnail && /\.(mp4|mov)$/i.test(currentPost.thumbnail) ? (
              <video
                key={currentPost.thumbnail}
                src={`${API_BASE}${currentPost.thumbnail}`}
                controls
                autoPlay
                preload="metadata"
                style={{ width: '100%', height: '100%', objectFit: 'contain' }}
              />
            ) : currentPost?.thumbnail ? (
              <img
                src={`${API_BASE}${currentPost.thumbnail}`}
                alt={t("Review Media")}
                style={{ width: '100%', height: '100%', objectFit: 'contain' }}
              />
            ) : (
              <div style={{ width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff' }}>{t("No Media")}</div>
            )}
          </div>

          {/* Right: Editor Panel */}
          <div className="card" style={{ width: '420px', display: 'flex', flexDirection: 'column', gap: '14px', overflowY: 'auto', padding: '20px' }}>
            {/* Top Navigation Row */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid var(--border)', paddingBottom: '10px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <button className="btn btn-sm" onClick={prevPost} disabled={currentIndex === 0} title={t("مورد قبلی")}>
                  <ChevronRight size={16} />
                </button>
                <span style={{ fontWeight: 600, fontSize: '14px' }}>
                  {pageOffset + currentIndex + 1} / {pageOffset + posts.length}
                </span>
                <button className="btn btn-sm" onClick={nextPost} disabled={currentIndex >= posts.length - 1 && !hasMore} title={t("مورد بعدی")}>
                  <ChevronLeft size={16} />
                </button>
              </div>

              <span style={{ color: 'var(--text-secondary)', fontSize: '13px' }}>@{currentPost?.owner_username}</span>
              <button className="close-btn" type="button" aria-label={t("بستن")} onClick={() => navigate('/library')}>
                <X size={18} />
              </button>
            </div>

            {/* Original Caption */}
            <div className="meta-group">
              <label className="meta-label">{t("کپشن اصلی اینستاگرام")}</label>
              <div style={{ fontSize: '13px', color: 'var(--text-secondary)', maxHeight: '110px', overflowY: 'auto', background: 'var(--bg-main)', padding: '10px', borderRadius: '6px', border: '1px solid var(--border)', whiteSpace: 'pre-wrap' }}>
                {currentPost?.caption || t('بدون کپشن')}
              </div>
            </div>

            {/* Owner & Meta info */}
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', color: 'var(--text-secondary)', background: 'var(--bg-main)', padding: '8px 12px', borderRadius: '6px' }}>
              <span>@{currentPost?.owner_username || 'نامشخص'}</span>
              <span>{t("اطمینان هوش مصنوعی:")} {currentPost?.ai_confidence ? `${Math.round(Number(currentPost.ai_confidence) * 100)}%` : '—'}</span>
            </div>

            {/* AI Category Input */}
            <div className="meta-group">
              <label className="meta-label" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <Sparkles size={14} color="var(--primary)" /> {t("دسته‌بندی هوش مصنوعی")}
              </label>
              <input
                type="text"
                className="meta-input"
                placeholder={t("مثال: Tech/AI یا Education")}
                value={formData.category}
                onChange={(e) => setFormData({ ...formData, category: e.target.value })}
              />
            </div>

            {/* AI Tags Input */}
            <div className="meta-group">
              <label className="meta-label">{t("تگ‌ها و کلیدواژه‌ها")}</label>
              <input
                type="text"
                className="meta-input"
                placeholder={t("تگ‌ها با کاما جدا شوند")}
                value={formData.tags}
                onChange={(e) => setFormData({ ...formData, tags: e.target.value })}
              />
            </div>

            {/* AI Summary Input */}
            <div className="meta-group">
              <label className="meta-label">{t("خلاصه فارسی / توضیحات هوش مصنوعی")}</label>
              <textarea
                className="meta-textarea"
                style={{ minHeight: '90px' }}
                placeholder={t("خلاصه تولیدشده توسط مدل...")}
                value={formData.summary}
                onChange={(e) => setFormData({ ...formData, summary: e.target.value })}
              />
            </div>

            {/* Action Buttons */}
            <div style={{ marginTop: 'auto', paddingTop: '10px', display: 'flex', gap: '10px' }}>
              <button
                className="btn"
                style={{ flex: 1, justifyContent: 'center' }}
                onClick={nextPost}
              >
                {t("رد کردن و بعدی")}
              </button>
              <button
                className="btn btn-primary"
                style={{ flex: 2, justifyContent: 'center', gap: '6px' }}
                onClick={handleSaveAndApprove}
              >
                <Check size={16} /> {t("تأیید و ذخیره")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default AIReview;
