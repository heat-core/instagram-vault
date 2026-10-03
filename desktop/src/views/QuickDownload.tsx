import { useState } from 'react';
import { useI18n } from '../i18n';
import { Link2, Download, CheckCircle, AlertCircle, Video, Image, ExternalLink, RefreshCw } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

const API_BASE = 'http://127.0.0.1:8000';

interface DownloadResult {
  success: boolean;
  message: string;
  already_exists?: boolean;
  post: {
    pk: string;
    shortcode: string;
    media_type: number;
    owner_username?: string;
    caption?: string;
    taken_at?: string;
    files?: string[];
  };
}

export default function QuickDownload() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [url, setUrl] = useState('');
  const [downloader, setDownloader] = useState<'public' | 'session'>('public');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<DownloadResult | null>(null);

  const handleDownload = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const cleanUrl = url.trim();
    if (!cleanUrl) {
      setError(t('لطفاً آدرس پست یا ریلز اینستاگرام را وارد کنید.'));
      return;
    }

    setLoading(true);
    setError('');
    setResult(null);

    try {
      const res = await fetch(`${API_BASE}/download/url`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: cleanUrl, downloader })
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || t('خطا در دانلود ویدیو'));
      }
      setResult(data);
    } catch (err: any) {
      setError(err.message || String(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="view-container animate-fade-in" style={{ padding: '24px', maxWidth: '850px', margin: '0 auto', display: 'flex', flexDirection: 'column', gap: '24px' }}>
      <div>
        <h1 className="view-title" style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <Link2 size={26} color="var(--primary)" /> {t('دانلود تکی با لینک')}
        </h1>
        <p style={{ color: 'var(--text-secondary)', marginTop: '4px' }}>
          {t('لینک هر پست یا ریلز اینستاگرام را وارد کنید تا مستقیماً با بالاترین کیفیت دانلود و در آرشیو شما ذخیره شود.')}
        </p>
      </div>

      <div className="card" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '18px' }}>
        <form onSubmit={handleDownload} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div>
            <label style={{ display: 'block', marginBottom: '8px', fontWeight: 500 }}>
              {t('آدرس ویدیو یا پست اینستاگرام:')}
            </label>
            <div style={{ display: 'flex', gap: '10px' }}>
              <input
                type="text"
                className="meta-input"
                dir="ltr"
                style={{ flex: 1, padding: '12px 16px', fontSize: '14px', fontFamily: 'monospace' }}
                placeholder="https://www.instagram.com/reel/C.../ یا https://www.instagram.com/p/.../"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                disabled={loading}
              />
              {url && (
                <button
                  type="button"
                  className="btn"
                  onClick={() => { setUrl(''); setError(''); setResult(null); }}
                  disabled={loading}
                  style={{ minWidth: '40px' }}
                >
                  ✕
                </button>
              )}
            </div>
          </div>

          <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: '12px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
              <span style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>{t('حالت دانلود:')}</span>
              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer', fontSize: '13px' }}>
                <input
                  type="radio"
                  name="downloader"
                  value="public"
                  checked={downloader === 'public'}
                  onChange={() => setDownloader('public')}
                />
                {t('عمومی (بدون لاگین - پیشنهادی برای ریلز)')}
              </label>
              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer', fontSize: '13px' }}>
                <input
                  type="radio"
                  name="downloader"
                  value="session"
                  checked={downloader === 'session'}
                  onChange={() => setDownloader('session')}
                />
                {t('با سشن اینستاگرام')}
              </label>
            </div>

            <button
              type="submit"
              className="btn btn-primary"
              disabled={loading || !url.trim()}
              style={{ padding: '10px 24px', display: 'flex', alignItems: 'center', gap: '8px' }}
            >
              {loading ? (
                <>
                  <RefreshCw size={18} className="animate-spin" />
                  {t('در حال دانلود...')}
                </>
              ) : (
                <>
                  <Download size={18} />
                  {t('دانلود مستقیم')}
                </>
              )}
            </button>
          </div>
        </form>

        {error && (
          <div role="alert" style={{
            display: 'flex', alignItems: 'center', gap: '10px',
            padding: '12px 16px', borderRadius: '8px',
            background: 'rgba(239, 68, 68, 0.1)', color: 'var(--error)', border: '1px solid rgba(239, 68, 68, 0.3)'
          }}>
            <AlertCircle size={20} />
            <span>{error}</span>
          </div>
        )}
      </div>

      {result && result.post && (
        <div className="card animate-fade-in" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px', borderColor: 'var(--primary)' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ display: 'flex', alignItems: 'center', gap: '8px', color: result.already_exists ? 'var(--primary)' : 'var(--success)', fontWeight: 600 }}>
              <CheckCircle size={20} /> {result.already_exists ? t('این پست قبلاً در آرشیو شما ذخیره شده است.') : t('ویدیو با موفقیت دانلود و در آرشیو ثبت شد!')}
            </span>
            <span className="badge" style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
              {result.post.media_type === 2 ? <Video size={14} /> : <Image size={14} />}
              {result.post.media_type === 2 ? t('ویدیو / ریلز') : t('تصویر')}
            </span>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', background: 'var(--bg-main)', padding: '16px', borderRadius: '8px' }}>
            {result.post.files && result.post.files[0] && result.post.files[0].endsWith('.mp4') ? (
              <video
                controls
                src={`http://127.0.0.1:8000${result.post.files[0]}`}
                style={{ width: '100%', maxHeight: '420px', borderRadius: '6px', background: '#000' }}
              />
            ) : result.post.files && result.post.files[0] ? (
              <img
                src={`http://127.0.0.1:8000${result.post.files[0]}`}
                alt="Downloaded media"
                style={{ width: '100%', maxHeight: '420px', objectFit: 'contain', borderRadius: '6px' }}
              />
            ) : null}

            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px', fontSize: '13px', color: 'var(--text-secondary)' }}>
              <div><strong>{t('شناسه:')}</strong> <code dir="ltr">{result.post.pk}</code></div>
              <div><strong>{t('کد کوتاه:')}</strong> <code dir="ltr">{result.post.shortcode}</code></div>
              {result.post.owner_username && <div><strong>{t('صاحب پست:')}</strong> @{result.post.owner_username}</div>}
            </div>

            {result.post.caption && (
              <p style={{ fontSize: '13px', whiteSpace: 'pre-wrap', maxHeight: '100px', overflowY: 'auto' }}>
                {result.post.caption}
              </p>
            )}
          </div>

          <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
            <button
              className="btn"
              onClick={() => { setUrl(''); setResult(null); }}
            >
              {t('دانلود ویدیوی دیگر')}
            </button>
            <button
              className="btn btn-primary"
              onClick={() => navigate(`/library?search=${result.post.shortcode}`)}
              style={{ display: 'flex', alignItems: 'center', gap: '6px' }}
            >
              <ExternalLink size={16} />
              {t('مشاهده در کتابخانه')}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
