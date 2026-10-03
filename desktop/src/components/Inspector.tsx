import { useI18n } from '../i18n';
import { useState, useEffect, useRef } from 'react';
import { X, ChevronLeft, ChevronRight, Save, Maximize2, ExternalLink, Copy, Check, Sparkles, Tag, User, Folder, Download, FolderOpen, Mic, Play, Pause, RotateCcw, RotateCw, Volume2, VolumeX } from 'lucide-react';
import { createPortal } from 'react-dom';
import type { Post, CustomCategory } from './MediaCard';

interface InspectorProps {
  post: Post | null;
  isOpen: boolean;
  onClose: () => void;
  onSave: (pk: string, data: any) => void;
}

const API_BASE = 'http://127.0.0.1:8000';

const Inspector = ({ post, isOpen, onClose, onSave }: InspectorProps) => {
  const { t, language } = useI18n();
  const [currentIndex, setCurrentIndex] = useState(0);
  const [zoomed, setZoomed] = useState(false);
  const [copiedLink, setCopiedLink] = useState(false);
  const [copiedCaption, setCopiedCaption] = useState(false);
  const [copiedTranscript, setCopiedTranscript] = useState(false);
  const [availableCategories, setAvailableCategories] = useState<CustomCategory[]>([]);
  const [selectedCustomCategories, setSelectedCustomCategories] = useState<number[]>([]);
  const [formData, setFormData] = useState({
    caption: '',
    category: '',
    tags: '',
    summary: '',
    transcript: ''
  });

  // Video player controls state
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [isPlaying, setIsPlaying] = useState(true);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [playbackRate, setPlaybackRate] = useState(1.0);
  const [volume, setVolume] = useState<number>(() => {
    const saved = localStorage.getItem('videoPlayerVolume');
    return saved !== null ? Number(saved) : 1.0;
  });
  const [isMuted, setIsMuted] = useState(false);

  useEffect(() => {
    if (isOpen) {
      fetch(`${API_BASE}/custom-categories`)
        .then(res => res.json())
        .then(data => {
          if (Array.isArray(data)) setAvailableCategories(data);
        })
        .catch(() => {});
    }
  }, [isOpen]);

  useEffect(() => {
    if (post) {
      setCurrentIndex(0);
      setZoomed(false);
      setCopiedLink(false);
      setCopiedCaption(false);
      setCopiedTranscript(false);
      setCurrentTime(0);
      setDuration(0);
      setIsPlaying(true);
      setFormData({
        caption: post.caption || '',
        category: post.ai_category || '',
        tags: post.ai_tags || '',
        summary: post.ai_summary || '',
        transcript: post.transcript || ''
      });
      setSelectedCustomCategories((post.custom_categories || []).map(c => c.id));
    }
  }, [post]);

  const currentMediaUrl = post?.files?.length ? `${API_BASE}${post.files[currentIndex]}` : null;
  const isVideo = /\.(mp4|mov)$/i.test(currentMediaUrl || '') || post?.media_type === 2;
  const currentFilePath = (() => {
    if (!post?.file_paths?.length) return null;
    if (isVideo) {
      const vid = post.file_paths.find(f => /\.(mp4|mov)$/i.test(f));
      if (vid) return vid;
    }
    return post.file_paths[currentIndex] || post.file_paths[0] || null;
  })();

  // Media player handlers
  const formatTime = (secs: number) => {
    if (!Number.isFinite(secs) || secs < 0) return '00:00';
    const m = Math.floor(secs / 60);
    const s = Math.floor(secs % 60);
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  };

  const handleTogglePlay = () => {
    if (!videoRef.current) return;
    if (videoRef.current.paused) {
      videoRef.current.play().catch(() => {});
    } else {
      videoRef.current.pause();
    }
  };

  const handleSeek = (seconds: number) => {
    if (!videoRef.current) return;
    const target = Math.max(0, Math.min(videoRef.current.duration || 0, videoRef.current.currentTime + seconds));
    videoRef.current.currentTime = target;
    setCurrentTime(target);
  };

  const handleRateChange = (rate: number) => {
    setPlaybackRate(rate);
    if (videoRef.current) {
      videoRef.current.playbackRate = rate;
    }
  };

  const handleVolumeChange = (newVol: number) => {
    const clamped = Math.max(0, Math.min(1, newVol));
    setVolume(clamped);
    localStorage.setItem('videoPlayerVolume', String(clamped));
    if (videoRef.current) {
      videoRef.current.volume = clamped;
      if (clamped > 0 && isMuted) {
        setIsMuted(false);
        videoRef.current.muted = false;
      }
    }
  };

  const handleToggleMute = () => {
    if (!videoRef.current) return;
    const next = !isMuted;
    setIsMuted(next);
    videoRef.current.muted = next;
  };

  // Keyboard shortcuts (Space, ArrowLeft, ArrowRight, ArrowUp, ArrowDown, M, F, Escape)
  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === 'INPUT' ||
         target.tagName === 'TEXTAREA' ||
         target.isContentEditable ||
         target.getAttribute('role') === 'textbox')
      ) {
        return;
      }

      if (event.key === 'Escape') {
        if (zoomed) setZoomed(false);
        else onClose();
        return;
      }

      if (!isVideo || !videoRef.current) return;

      if (event.code === 'Space') {
        event.preventDefault();
        handleTogglePlay();
      } else if (event.key === 'ArrowLeft') {
        event.preventDefault();
        handleSeek(-5);
      } else if (event.key === 'ArrowRight') {
        event.preventDefault();
        handleSeek(5);
      } else if (event.key === 'ArrowUp') {
        event.preventDefault();
        handleVolumeChange(volume + 0.1);
      } else if (event.key === 'ArrowDown') {
        event.preventDefault();
        handleVolumeChange(volume - 0.1);
      } else if (event.key === 'm' || event.key === 'M') {
        event.preventDefault();
        handleToggleMute();
      } else if (event.key === 'f' || event.key === 'F') {
        event.preventDefault();
        setZoomed(prev => !prev);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose, zoomed, isVideo, isPlaying, isMuted, volume, playbackRate]);

  if (!post) return null;

  const handleNext = () => {
    setCurrentIndex((prev) => (prev + 1) % post.files.length);
  };

  const handlePrev = () => {
    setCurrentIndex((prev) => (prev - 1 + post.files.length) % post.files.length);
  };

  const postUrl = post.shortcode
    ? `https://www.instagram.com/p/${post.shortcode}/`
    : `https://www.instagram.com/p/${post.pk}/`;

  const handleCopyLink = async () => {
    try {
      await navigator.clipboard.writeText(postUrl);
      setCopiedLink(true);
      setTimeout(() => setCopiedLink(false), 2000);
    } catch {
      // ignore
    }
  };

  const handleCopyCaption = async () => {
    if (!post.caption) return;
    try {
      await navigator.clipboard.writeText(post.caption);
      setCopiedCaption(true);
      setTimeout(() => setCopiedCaption(false), 2000);
    } catch {
      // ignore
    }
  };

  const handleCopyTranscript = async () => {
    if (!formData.transcript) return;
    try {
      await navigator.clipboard.writeText(formData.transcript);
      setCopiedTranscript(true);
      setTimeout(() => setCopiedTranscript(false), 2000);
    } catch {
      // ignore
    }
  };

  const handleOpenInstagram = () => {
    window.open(postUrl, '_blank', 'noopener,noreferrer');
  };

  const handleSave = () => {
    onSave(post.pk, {
      ...formData,
      caption: formData.caption,
      custom_category_ids: selectedCustomCategories,
      ...(['DOWNLOAD_OK', 'ANALYSIS_OK', 'REVIEW_REQUIRED'].includes(post.status) ? { status: 'APPROVED' } : {})
    });
  };

  if (!post) return null;

  return createPortal(
    <>
      <div 
        className={`inspector-panel ${isOpen ? 'open' : ''}`}
        dir={document.documentElement.dir || (language === 'fa' ? 'rtl' : 'ltr')}
      >
        {/* Header */}
        <div className="inspector-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <h3 style={{ margin: 0, fontSize: '16px', fontWeight: 600 }}>{t("جزئیات پست")}</h3>
            <span className="badge" style={{ fontSize: '11px' }}>{t(post.status)}</span>
          </div>
          <button className="close-btn" type="button" aria-label={t("بستن جزئیات پست")} onClick={onClose}>
            <X size={18} />
          </button>
        </div>

        {/* Media Preview Box */}
        <div 
          className="inspector-media-container"
          draggable={!!currentFilePath}
          onDragStart={(e) => {
            if (currentFilePath && (window as any).appBridge?.startDrag) {
              e.stopPropagation();
              (window as any).appBridge.startDrag(currentFilePath);
            }
          }}
          title={currentFilePath ? t("می‌توانید این فایل را بکشید و روی دسکتاپ ویندوز رها کنید (Drag to Desktop)") : undefined}
          style={{ cursor: currentFilePath ? 'grab' : 'default' }}
        >
          {currentMediaUrl ? (
            isVideo ? (
              <video
                ref={videoRef}
                src={currentMediaUrl}
                className="inspector-media"
                autoPlay
                loop
                muted={isMuted}
                draggable={false}
                onClick={handleTogglePlay}
                onTimeUpdate={() => {
                  if (videoRef.current) setCurrentTime(videoRef.current.currentTime);
                }}
                onLoadedMetadata={() => {
                  if (videoRef.current) {
                    setDuration(videoRef.current.duration || 0);
                    videoRef.current.playbackRate = playbackRate;
                    videoRef.current.volume = volume;
                    videoRef.current.muted = isMuted;
                  }
                }}
                onPlay={() => setIsPlaying(true)}
                onPause={() => setIsPlaying(false)}
                style={{ cursor: 'pointer' }}
              />
            ) : (
              <img 
                src={currentMediaUrl} 
                className="inspector-media" 
                alt={t("پیش‌نمایش رسانه")} 
                draggable={false} 
                onDragStart={(e) => e.preventDefault()} 
              />
            )
          ) : (
            <div style={{ color: 'var(--text-secondary)' }}>{t("رسانه‌ای موجود نیست")}</div>
          )}

          {post.files.length > 1 && (
            <>
              <button className="carousel-btn carousel-prev" onClick={handlePrev} aria-label={t("مورد قبلی")}>
                <ChevronLeft size={20} />
              </button>
              <button className="carousel-btn carousel-next" onClick={handleNext} aria-label={t("مورد بعدی")}>
                <ChevronRight size={20} />
              </button>
              <div style={{ position: 'absolute', bottom: 10, background: 'rgba(0,0,0,0.65)', backdropFilter: 'blur(4px)', padding: '3px 10px', borderRadius: '12px', fontSize: '12px', color: '#fff' }}>
                {currentIndex + 1} / {post.files.length}
              </div>
            </>
          )}
        </div>

        {/* Advanced Video Player Controls */}
        {isVideo && currentMediaUrl && (
          <div
            style={{
              padding: '10px 16px',
              background: 'rgba(15, 23, 42, 0.95)',
              borderBottom: '1px solid var(--border-color)',
              display: 'flex',
              flexDirection: 'column',
              gap: '8px'
            }}
          >
            {/* Timeline Progress Bar & Time */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <span style={{ fontSize: '11px', fontFamily: 'monospace', color: 'var(--text-secondary)', minWidth: '42px', direction: 'ltr' }}>
                {formatTime(currentTime)}
              </span>
              <input
                type="range"
                min={0}
                max={duration || 100}
                step={0.1}
                value={currentTime}
                onChange={(e) => {
                  const val = Number(e.target.value);
                  if (videoRef.current) {
                    videoRef.current.currentTime = val;
                    setCurrentTime(val);
                  }
                }}
                style={{
                  flex: 1,
                  height: '4px',
                  borderRadius: '2px',
                  accentColor: 'var(--primary)',
                  cursor: 'pointer'
                }}
                aria-label={t("خط پیشرفت ویدیو")}
              />
              <span style={{ fontSize: '11px', fontFamily: 'monospace', color: 'var(--text-secondary)', minWidth: '42px', direction: 'ltr' }}>
                {formatTime(duration)}
              </span>
            </div>

            {/* Controls Row: Play/Pause, -5s, +5s, Speed Pills, Volume */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={handleTogglePlay}
                  title={isPlaying ? t("توقف (Space)") : t("پخش (Space)")}
                  style={{ padding: '4px 8px', borderRadius: '6px' }}
                >
                  {isPlaying ? <Pause size={14} /> : <Play size={14} fill="currentColor" />}
                </button>
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={() => handleSeek(-5)}
                  title={t("۵ ثانیه عقب (کلید چپ)")}
                  style={{ padding: '4px 8px', fontSize: '11px', gap: '3px' }}
                >
                  <RotateCcw size={13} />
                  <span>5s-</span>
                </button>
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={() => handleSeek(5)}
                  title={t("۵ ثانیه جلو (کلید راست)")}
                  style={{ padding: '4px 8px', fontSize: '11px', gap: '3px' }}
                >
                  <RotateCw size={13} />
                  <span>5s+</span>
                </button>
              </div>

              {/* Playback Speed Pills */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '4px', background: 'var(--bg-tertiary)', padding: '2px 4px', borderRadius: '16px' }}>
                {[0.75, 1.0, 1.25, 1.5, 2.0].map((rate) => (
                  <button
                    key={rate}
                    type="button"
                    onClick={() => handleRateChange(rate)}
                    style={{
                      background: playbackRate === rate ? 'var(--primary)' : 'transparent',
                      color: playbackRate === rate ? '#fff' : 'var(--text-secondary)',
                      border: 'none',
                      borderRadius: '12px',
                      padding: '2px 6px',
                      fontSize: '11px',
                      fontWeight: playbackRate === rate ? 600 : 400,
                      cursor: 'pointer',
                      transition: 'all 0.15s ease'
                    }}
                  >
                    {rate}x
                  </button>
                ))}
              </div>

              {/* Volume Slider & Mute Toggle */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={handleToggleMute}
                  title={isMuted ? t("صدا دار کن (M)") : t("بی‌صدا کن (M)")}
                  style={{ padding: '4px 6px', border: 'none', background: 'transparent' }}
                >
                  {isMuted || volume === 0 ? <VolumeX size={15} color="var(--warning)" /> : <Volume2 size={15} />}
                </button>
                <input
                  type="range"
                  min={0}
                  max={1}
                  step={0.05}
                  value={isMuted ? 0 : volume}
                  onChange={(e) => handleVolumeChange(Number(e.target.value))}
                  style={{ width: '60px', height: '4px', accentColor: 'var(--primary)', cursor: 'pointer' }}
                  aria-label={t("میزان صدا")}
                />
              </div>
            </div>

            {/* Quick shortcuts hint */}
            <div style={{ fontSize: '10px', color: 'var(--text-muted)', textAlign: 'center', borderTop: '1px solid rgba(255,255,255,0.05)', paddingTop: '4px' }}>
              {t("میانبرها: Space (پخش) · جهت‌نما (±۵ ثانیه / صدا) · M (صدا) · F (تمام صفحه)")}
            </div>
          </div>
        )}

        {/* Scrollable Body Container */}
        <div className="inspector-scroll-area">
          {/* Action Toolbar */}
          <div className="inspector-toolbar">
          {currentMediaUrl && (
            <button className="btn btn-sm" type="button" onClick={() => setZoomed(true)} title={t("نمایش بزرگ رسانه")}>
              <Maximize2 size={14} /> {t("نمایش بزرگ")}
            </button>
          )}
          {currentFilePath && (
            <>
              <button 
                className="btn btn-sm" 
                type="button" 
                onClick={() => (window as any).appBridge?.showInFolder?.(currentFilePath)} 
                title={t("نمایش در پوشه ویندوز")}
              >
                <FolderOpen size={14} /> {t("نمایش در پوشه")}
              </button>
              <button 
                className="btn btn-sm" 
                type="button" 
                onClick={() => (window as any).appBridge?.saveMediaAs?.(currentFilePath)} 
                title={t("ذخیره به عنوان...")}
              >
                <Download size={14} /> {t("ذخیره فایل...")}
              </button>
            </>
          )}
          <button className="btn btn-sm" type="button" onClick={handleOpenInstagram} title={t("باز کردن در اینستاگرام")}>
            <ExternalLink size={14} /> {t("اینستاگرام")}
          </button>
          <button className="btn btn-sm" type="button" onClick={handleCopyLink} title={t("کپی لینک پست")}>
            {copiedLink ? <Check size={14} color="var(--success)" /> : <Copy size={14} />}
            {copiedLink ? t("لینک کپی شد") : t("کپی لینک")}
          </button>
        </div>

        {/* Body Form & Metadata */}
        <div className="inspector-body">
          {/* Creator & Publishing Metadata */}
          <div className="meta-group">
            <label className="meta-label">{t("منتشرکنندهٔ اصلی")}</label>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '14px', fontWeight: 600 }}>
              <User size={15} color="var(--accent-secondary)" />
              <span dir="ltr">@{post.owner_username || 'Unknown'}</span>
              {post.owner_id && <span style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>({post.owner_id})</span>}
            </div>

            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px', marginTop: '10px', fontSize: '12px', color: 'var(--text-secondary)' }}>
              {post.shortcode && (
                <div>{t("کد پست:")} <code dir="ltr" style={{ color: 'var(--text-primary)' }}>{post.shortcode}</code></div>
              )}
              {post.published_at_utc && (
                <div>{t("انتشار:")} <span dir="ltr">{post.published_at_utc}</span></div>
              )}
              {post.saved_at_utc && (
                <div>{t("ذخیره:")} <span dir="ltr">{post.saved_at_utc}</span></div>
              )}
              {post.liked_at_utc && (
                <div>{t("لایک:")} <span dir="ltr">{post.liked_at_utc}</span></div>
              )}
            </div>
          </div>

          {/* Quality Information */}
          {!!post.quality?.length && (
            <div className="meta-group">
              <label className="meta-label">{t("کیفیت واقعی فایل‌ها")}</label>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', fontSize: '12px' }}>
                {post.quality.map((item, index) => {
                  const target = localStorage.getItem('qualityTarget') === 'hd' ? 720 : 1080;
                  const low = item.width && item.height && (Math.min(item.width, item.height) < target || (post.files[index] && /\.(mp4|mov)$/i.test(post.files[index]) && (item.bitrate_bps || 0) < 1000000));
                  return (
                    <div key={index} style={{ background: 'var(--bg-tertiary)', padding: '6px 10px', borderRadius: '4px' }}>
                      <span dir="ltr">
                        #{index + 1}: {item.width || '?'}×{item.height || '?'} px · {item.size_bytes ? (item.size_bytes / 1048576).toFixed(2) : '?'} MB
                        {item.bitrate_bps ? ` · ${(item.bitrate_bps / 1000000).toFixed(2)} Mb/s` : ''}
                      </span>
                      {low && <span style={{ color: 'var(--warning)', marginRight: '6px' }}> {t("· کمتر از هدف")}</span>}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Caption & Description */}
          <div className="meta-group">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
              <label className="meta-label" style={{ margin: 0 }}>{t("کپشن و توضیحات (فارسی / انگلیسی)")}</label>
              {formData.caption && (
                <button
                  type="button"
                  className="btn btn-sm"
                  style={{ padding: '2px 8px', fontSize: '11px', display: 'flex', alignItems: 'center', gap: '4px' }}
                  onClick={handleCopyCaption}
                >
                  {copiedCaption ? <Check size={12} color="var(--success)" /> : <Copy size={12} />}
                  {copiedCaption ? t("کپشن کپی شد") : t("کپی کپشن")}
                </button>
              )}
            </div>
            <textarea
              className="meta-textarea"
              dir="auto"
              style={{
                minHeight: '90px',
                maxHeight: '180px',
                fontSize: '13px',
                lineHeight: 1.6,
                fontFamily: 'inherit',
                direction: /[\u0600-\u06FF]/.test(formData.caption) ? 'rtl' : 'ltr',
                textAlign: /[\u0600-\u06FF]/.test(formData.caption) ? 'right' : 'left'
              }}
              placeholder={t("متن کپشن یا توضیحات پست...")}
              value={formData.caption}
              onChange={(e) => setFormData({ ...formData, caption: e.target.value })}
            />
          </div>

          {/* Custom User Categories & Folders */}
          {availableCategories.length > 0 && (
            <div className="meta-group">
              <label className="meta-label" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <Folder size={14} color="var(--primary)" /> {t("دسته‌بندی‌های اختصاصی من (پوشه‌ها)")}
              </label>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginTop: '6px' }}>
                {availableCategories.map((cat) => {
                  const isAssigned = selectedCustomCategories.includes(cat.id);
                  return (
                    <button
                      key={cat.id}
                      type="button"
                      onClick={() => {
                        if (isAssigned) {
                          setSelectedCustomCategories(selectedCustomCategories.filter(id => id !== cat.id));
                        } else {
                          setSelectedCustomCategories([...selectedCustomCategories, cat.id]);
                        }
                      }}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '6px',
                        padding: '4px 10px',
                        borderRadius: '16px',
                        fontSize: '12px',
                        cursor: 'pointer',
                        border: isAssigned ? `2px solid ${cat.color || 'var(--primary)'}` : '1px solid var(--border)',
                        background: isAssigned ? `${cat.color || 'var(--primary)'}22` : 'var(--bg-tertiary)',
                        color: isAssigned ? (cat.color || 'var(--text-primary)') : 'var(--text-secondary)',
                        fontWeight: isAssigned ? 600 : 400,
                        transition: 'all 0.15s ease'
                      }}
                    >
                      <span
                        style={{
                          width: '8px',
                          height: '8px',
                          borderRadius: '50%',
                          backgroundColor: cat.color || 'var(--primary)'
                        }}
                      />
                      <span>{cat.name}</span>
                      {isAssigned && <Check size={12} />}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* Hashtags */}
          {post.original_hashtags && (
            <div className="meta-group">
              <label className="meta-label" style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                <Tag size={13} /> {t("هشتگ‌های اصلی")}
              </label>
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)', background: 'var(--bg-tertiary)', padding: '8px', borderRadius: '6px' }}>
                {post.original_hashtags}
              </div>
            </div>
          )}

          {/* Tagged Accounts */}
          {!!post.tagged_users?.length && (
            <div className="meta-group">
              <label className="meta-label">{t("حساب‌های تگ‌شده")}</label>
              <div style={{ fontSize: '12px', color: 'var(--accent-secondary)' }}>
                {post.tagged_users.map(user => `@${user.username}`).join(', ')}
              </div>
            </div>
          )}

          {/* AI Category Input */}
          <div className="meta-group">
            <label className="meta-label" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Sparkles size={13} color="var(--accent-primary)" /> {t("دسته‌بندی هوش مصنوعی")}
            </label>
            <input 
              type="text" 
              className="meta-input" 
              placeholder={t("مثال: Tech/AI یا Education")}
              value={formData.category} 
              onChange={(e) => setFormData({...formData, category: e.target.value})} 
            />
          </div>

          {/* AI Tags Input */}
          <div className="meta-group">
            <label className="meta-label">{t("تگ‌های AI (با ویرگول جدا کنید)")}</label>
            <input 
              type="text" 
              className="meta-input" 
              placeholder={t("تگ‌ها با کاما جدا شوند")}
              value={formData.tags} 
              onChange={(e) => setFormData({...formData, tags: e.target.value})} 
            />
          </div>

          {/* AI Summary Input */}
          <div className="meta-group">
            <label className="meta-label">{t("خلاصهٔ AI")}</label>
            <textarea 
              className="meta-textarea" 
              placeholder={t("خلاصه تولیدشده توسط مدل...")}
              value={formData.summary} 
              onChange={(e) => setFormData({...formData, summary: e.target.value})} 
            />
          </div>

          {/* Audio Transcript (Spoken words in Video/Reel) */}
          {(formData.transcript || post.media_type === 2) && (
            <div className="meta-group">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                <label className="meta-label" style={{ display: 'flex', alignItems: 'center', gap: '6px', margin: 0 }}>
                  <Mic size={14} color="var(--accent-primary)" /> {t("رونوشت صوتی و گفتار ویدیو")}
                </label>
                {formData.transcript && (
                  <button
                    type="button"
                    className="btn btn-sm"
                    style={{ padding: '2px 8px', fontSize: '11px', display: 'flex', alignItems: 'center', gap: '4px' }}
                    onClick={handleCopyTranscript}
                  >
                    {copiedTranscript ? <Check size={12} color="var(--success)" /> : <Copy size={12} />}
                    {copiedTranscript ? t("رونوشت کپی شد") : t("کپی متن صحبت‌ها")}
                  </button>
                )}
              </div>
              <textarea
                className="meta-textarea"
                dir="auto"
                style={{
                  minHeight: '80px',
                  maxHeight: '160px',
                  fontSize: '12px',
                  lineHeight: 1.5,
                  fontFamily: 'inherit',
                  direction: /[\u0600-\u06FF]/.test(formData.transcript) ? 'rtl' : 'ltr',
                  textAlign: /[\u0600-\u06FF]/.test(formData.transcript) ? 'right' : 'left'
                }}
                placeholder={t("متن استخراج‌شده از صدای ویدیو یا ریلز...")}
                value={formData.transcript}
                onChange={(e) => setFormData({ ...formData, transcript: e.target.value })}
              />
            </div>
          )}

          {/* Save Button */}
          <button className="btn btn-primary" style={{ width: '100%', justifyContent: 'center', padding: '12px', marginTop: '10px' }} onClick={handleSave}>
            <Save size={16} /> {post.status === 'DOWNLOAD_OK' || post.status === 'ANALYSIS_OK' ? t("ذخیره و تأیید") : t("ذخیره اطلاعات")}
          </button>
          {post.status === 'ORGANIZED' && (
            <p style={{ fontSize: '12px', color: 'var(--text-secondary)', textAlign: 'center', marginTop: '8px' }}>
              {t("پس از ذخیره، برای به‌روزرسانی پوشه‌ها «ساخت دسته‌بندی» را اجرا کنید.")}
            </p>
          )}
          </div>
        </div>
      </div>

      {/* Full-Screen Zoom Modal */}
      {zoomed && currentMediaUrl && createPortal(
        <div
          role="dialog"
          aria-modal="true"
          aria-label={t("نمای بزرگ رسانه")}
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 1000,
            background: 'rgba(0,0,0,0.95)',
            backdropFilter: 'blur(8px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '40px'
          }}
          onClick={() => setZoomed(false)}
        >
          <button
            className="btn"
            type="button"
            aria-label={t("بستن نمای بزرگ")}
            onClick={() => setZoomed(false)}
            style={{ position: 'absolute', top: 20, right: 20, zIndex: 1001, background: 'rgba(255,255,255,0.1)' }}
          >
            <X size={18} /> {t("بستن")}
          </button>
          <div onClick={(e) => e.stopPropagation()} style={{ maxWidth: '90vw', maxHeight: '90vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            {isVideo ? (
              <video src={currentMediaUrl} controls autoPlay style={{ maxWidth: '100%', maxHeight: '90vh', borderRadius: '8px' }} />
            ) : (
              <img src={currentMediaUrl} alt={t("رسانه در اندازهٔ بزرگ")} style={{ maxWidth: '100%', maxHeight: '90vh', objectFit: 'contain', borderRadius: '8px' }} />
            )}
          </div>
        </div>,
        document.body
      )}
    </>,
    document.body
  );
};

export default Inspector;
