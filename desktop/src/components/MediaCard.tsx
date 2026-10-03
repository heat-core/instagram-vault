import { useState, useMemo, useRef, useEffect } from 'react';
import { 
  Play, 
  Layers, 
  Bookmark, 
  Heart, 
  Folder, 
  FolderOpen, 
  Download, 
  Eye, 
  ExternalLink,
  Image as ImageIcon,
  Check
} from 'lucide-react';
import { useI18n } from '../i18n';

export interface CustomCategory {
  id: number;
  name: string;
  folder_name: string;
  color: string;
}

export interface Post {
  pk: string;
  id: string;
  shortcode: string;
  taken_at: number;
  media_type: number;
  caption: string;
  owner_username: string;
  owner_id: string;
  original_hashtags?: string;
  tagged_users?: { username: string; id?: string }[];
  published_at_utc?: string;
  saved_at_utc?: string;
  liked_at_utc?: string;
  is_saved?: number;
  is_liked?: number;
  quality?: { width: number | null; height: number | null; size_bytes: number | null; bitrate_bps: number | null }[];
  ai_confidence?: string;
  ai_categories?: string;
  status: string;
  ai_summary?: string;
  ai_tags?: string;
  ai_category?: string;
  transcript?: string;
  custom_categories?: CustomCategory[];
  files: string[];
  file_paths?: string[];
  thumbnail: string | null;
}

interface MediaCardProps {
  post: Post;
  onClick: (post: Post) => void;
  selectable?: boolean;
  selected?: boolean;
  onToggleSelect?: (post: Post, selected: boolean) => void;
}

const API_BASE = 'http://127.0.0.1:8000';

const MediaCard = ({ post, onClick, selectable, selected, onToggleSelect }: MediaCardProps) => {
  const { t } = useI18n();
  const [copiedLink, setCopiedLink] = useState(false);
  const [isHovered, setIsHovered] = useState(false);
  const [videoProgress, setVideoProgress] = useState(0);
  const hoverTimeoutRef = useRef<any>(null);
  const videoPreviewRef = useRef<HTMLVideoElement>(null);

  const thumbnailUrl = post.thumbnail ? `${API_BASE}${post.thumbnail}` : '';
  const isRawVideoThumb = /\.(mp4|mov)$/i.test(thumbnailUrl);

  // 1: Photo, 2: Video, 8: Carousel
  const isVideo = useMemo(() => {
    if (Number(post.media_type) === 2) return true;
    if (post.files && post.files.some(f => /\.(mp4|mov|webm)$/i.test(f))) return true;
    if (post.file_paths && post.file_paths.some(f => /\.(mp4|mov|webm)$/i.test(f))) return true;
    if (isRawVideoThumb) return true;
    return false;
  }, [post.media_type, post.files, post.file_paths, isRawVideoThumb]);

  const isCarousel = post.media_type === 8;
  const primaryCustomCat = post.custom_categories && post.custom_categories.length > 0 ? post.custom_categories[0] : null;
  
  // Guarantee picking the actual media file (e.g. .mp4 for video) instead of .poster.jpg
  const targetFilePath = useMemo(() => {
    if (!post.file_paths || post.file_paths.length === 0) return null;
    if (isVideo) {
      const vid = post.file_paths.find(f => /\.(mp4|mov)$/i.test(f));
      if (vid) return vid;
    }
    return post.file_paths[0];
  }, [post.file_paths, isVideo]);

  // Video stream URL for hover preview
  const videoUrl = useMemo(() => {
    if (isRawVideoThumb && thumbnailUrl) return thumbnailUrl;
    if (post.files && post.files.length > 0) {
      const vid = post.files.find(f => /\.(mp4|mov|webm)$/i.test(f));
      if (vid) {
        if (vid.startsWith('http')) return vid;
        const clean = vid.replace(/\\/g, '/');
        return `${API_BASE}${clean.startsWith('/') ? '' : '/'}${clean}`;
      }
    }
    // Fallback: If post is video and has pk, use direct streaming endpoint
    if (isVideo && post.pk) {
      return `${API_BASE}/media-stream/${post.pk}`;
    }
    return null;
  }, [post.files, post.pk, isVideo, isRawVideoThumb, thumbnailUrl]);

  const handleMouseEnter = () => {
    if (isVideo && videoUrl) {
      if (hoverTimeoutRef.current) clearTimeout(hoverTimeoutRef.current);
      hoverTimeoutRef.current = setTimeout(() => {
        setIsHovered(true);
      }, 100);
    }
  };

  const handleMouseLeave = () => {
    if (hoverTimeoutRef.current) {
      clearTimeout(hoverTimeoutRef.current);
      hoverTimeoutRef.current = null;
    }
    if (videoPreviewRef.current) {
      try {
        videoPreviewRef.current.pause();
        videoPreviewRef.current.currentTime = 0;
      } catch (e) {}
    }
    setIsHovered(false);
    setVideoProgress(0);
  };

  // Explicitly ensure video plays when hovered
  useEffect(() => {
    if (isHovered && videoPreviewRef.current) {
      const vid = videoPreviewRef.current;
      vid.defaultMuted = true;
      vid.muted = true;
      vid.currentTime = 0;
      const playPromise = vid.play();
      if (playPromise !== undefined) {
        playPromise.catch((err) => {
          console.warn('Video hover preview play failed:', err);
        });
      }
    }
  }, [isHovered, videoUrl]);

  const postUrl = post.shortcode 
    ? `https://www.instagram.com/p/${post.shortcode}/` 
    : (post.original_hashtags || '');

  const handleCopyLink = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (postUrl) {
      navigator.clipboard.writeText(postUrl);
      setCopiedLink(true);
      setTimeout(() => setCopiedLink(false), 2000);
    }
  };

  return (
    <div 
      className={`media-card modern-card animate-fade-in ${selected ? 'selected-card' : ''} ${isHovered && isVideo ? 'is-video-previewing' : ''}`} 
      onClick={() => onClick(post)}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      draggable={!!targetFilePath}
      onDragStart={(e) => {
        if (targetFilePath && (window as any).appBridge?.startDrag) {
          e.stopPropagation();
          (window as any).appBridge.startDrag(targetFilePath);
        }
      }}
      title={targetFilePath ? t("می‌توانید این فایل را بکشید و روی دسکتاپ رها کنید (Drag to Desktop)") : undefined}
    >
      {/* Checkbox for bulk actions */}
      {selectable && (
        <div 
          className="media-card-select-box"
          onClick={(e) => {
            e.stopPropagation();
            onToggleSelect?.(post, !selected);
          }}
        >
          <input 
            type="checkbox" 
            checked={!!selected} 
            onChange={(e) => onToggleSelect?.(post, e.target.checked)}
            style={{ width: '18px', height: '18px', cursor: 'pointer', accentColor: 'var(--primary)' }}
          />
        </div>
      )}

      {/* Media Image / Video Preview */}
      <div className="media-thumbnail-wrapper">
        {isVideo && videoUrl && isHovered && (
          <video
            ref={videoPreviewRef}
            src={videoUrl}
            className="media-thumbnail media-video-preview"
            autoPlay
            loop
            muted
            playsInline
            draggable={false}
            onTimeUpdate={() => {
              if (videoPreviewRef.current) {
                const { currentTime, duration } = videoPreviewRef.current;
                if (duration > 0) {
                  setVideoProgress((currentTime / duration) * 100);
                }
              }
            }}
            onLoadedData={() => {
              if (videoPreviewRef.current) {
                videoPreviewRef.current.muted = true;
                videoPreviewRef.current.play().catch(() => {});
              }
            }}
            style={{
              position: 'absolute',
              inset: 0,
              width: '100%',
              height: '100%',
              objectFit: 'cover',
              zIndex: 3,
              pointerEvents: 'none'
            }}
          />
        )}
        {thumbnailUrl && !isRawVideoThumb ? (
          <img 
            src={thumbnailUrl} 
            alt={post.caption || t('Instagram Media')} 
            className="media-thumbnail" 
            loading="lazy" 
            decoding="async"
            draggable={false}
            onDragStart={(e) => e.preventDefault()}
          />
        ) : isRawVideoThumb ? (
          <div className="media-thumbnail-placeholder">
            <div className="play-pulse-circle">
              <Play size={24} fill="white" color="white" />
            </div>
            <span style={{ fontSize: '12px', fontWeight: 600, color: 'rgba(255,255,255,0.85)' }}>{t('ویدیو')}</span>
          </div>
        ) : (
          <div className="media-thumbnail-empty">
            <div className="empty-icon-box">
              <ImageIcon size={28} color="rgba(168, 85, 247, 0.7)" />
            </div>
            <span style={{ fontSize: '12px', color: 'var(--text-secondary)', fontWeight: 500 }}>
              {t('رسانه‌ای موجود نیست')}
            </span>
            <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
              {post.status === 'DISCOVERED' ? t('در انتظار دانلود') : t('بدون فایل')}
            </span>
          </div>
        )}

        {/* Sleek Neon Timeline Bar on Video Hover */}
        {isVideo && isHovered && videoUrl && (
          <div className="video-preview-timeline-track">
            <div 
              className="video-preview-timeline-fill" 
              style={{ width: `${videoProgress}%` }}
            />
          </div>
        )}
      </div>

      {/* Top Floating Glass Badges */}
      <div className="media-card-top-bar">
        {post.owner_username ? (
          <span className="media-owner-badge" dir="ltr" title={`@${post.owner_username}`}>
            @{post.owner_username}
          </span>
        ) : <span />}

        <div className="media-badges-group">
          {post.is_saved === 1 && (
            <div className="media-indicator-pill saved-pill" title={t("ذخیره‌شده در اینستاگرام")}>
              <Bookmark size={11} fill="currentColor" />
            </div>
          )}
          {post.is_liked === 1 && (
            <div className="media-indicator-pill liked-pill" title={t("لایک‌شده در اینستاگرام")}>
              <Heart size={11} fill="currentColor" />
            </div>
          )}
          {isVideo && (
            <div 
              className={`media-indicator-pill video-pill ${isHovered && videoUrl ? 'preview-active' : ''}`} 
              title={isHovered && videoUrl ? t("در حال پیش‌نمایش ویدیو") : t("ویدیو")}
            >
              <Play size={10} fill="currentColor" />
              {isHovered && videoUrl && (
                <span className="preview-label">{t('پخش')}</span>
              )}
            </div>
          )}
          {isCarousel && (
            <div className="media-indicator-pill carousel-pill" title={t("چنداسلایدی")}>
              <Layers size={11} />
            </div>
          )}
        </div>
      </div>

      {/* Hover Floating Action Dock */}
      <div className="media-card-hover-overlay">
        <div className="media-actions-dock" onClick={(e) => e.stopPropagation()}>
          <button
            type="button"
            className="dock-action-btn"
            title={t("مشاهده جزئیات و پیش‌نمایش")}
            onClick={() => onClick(post)}
          >
            <Eye size={15} />
          </button>

          {targetFilePath && (
            <>
              <button
                type="button"
                className="dock-action-btn"
                title={t("نمایش در پوشه ویندوز")}
                onClick={() => (window as any).appBridge?.showInFolder?.(targetFilePath)}
              >
                <FolderOpen size={15} />
              </button>
              <button
                type="button"
                className="dock-action-btn"
                title={t("ذخیره به عنوان...")}
                onClick={() => (window as any).appBridge?.saveMediaAs?.(targetFilePath)}
              >
                <Download size={15} />
              </button>
            </>
          )}

          {postUrl && (
            <button
              type="button"
              className="dock-action-btn"
              title={copiedLink ? t("کپی شد!") : t("کپی لینک اینستاگرام")}
              onClick={handleCopyLink}
            >
              {copiedLink ? <Check size={15} color="#22c55e" /> : <ExternalLink size={15} />}
            </button>
          )}
        </div>

        {post.caption && (
          <div className="media-hover-caption">
            {post.caption.slice(0, 90)}{post.caption.length > 90 ? '...' : ''}
          </div>
        )}
      </div>

      {/* Bottom Category & Status Pill Bar */}
      {(primaryCustomCat || post.ai_category || post.status) && (
        <div className="media-card-bottom-bar">
          {primaryCustomCat ? (
            <span 
              className="media-category-chip custom-cat-chip" 
              style={{ 
                color: primaryCustomCat.color || '#a855f7',
                borderColor: `${primaryCustomCat.color || '#a855f7'}40`,
                background: `${primaryCustomCat.color || '#a855f7'}18`
              }}
            >
              <Folder size={11} />
              <span>{primaryCustomCat.name}</span>
            </span>
          ) : post.ai_category ? (
            <span className="media-category-chip ai-cat-chip">
              {post.ai_category.split('/').pop()}
            </span>
          ) : null}

          {post.status && post.status !== 'DOWNLOAD_OK' && (
            <span className={`media-status-chip status-${post.status.toLowerCase()}`}>
              {t(post.status)}
            </span>
          )}
        </div>
      )}
    </div>
  );
};

export default MediaCard;
