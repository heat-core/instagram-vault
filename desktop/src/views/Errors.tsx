import { useI18n } from '../i18n';
import { useState, useEffect } from 'react';
import { AlertOctagon, RotateCw, List } from 'lucide-react';
import type { Post } from '../components/MediaCard';

const API_BASE = 'http://127.0.0.1:8000';

const Errors = () => {
  const { t, language } = useI18n();
  const [failedPosts, setFailedPosts] = useState<Post[]>([]);
  const [logs, setLogs] = useState<any[]>([]);

  const fetchData = async () => {
    try {
      // Fetch failed posts
      const params = new URLSearchParams({ status: 'DOWNLOAD_FAILED' });
      const postsRes = await fetch(`${API_BASE}/posts?${params.toString()}`);
      const postsData = await postsRes.json();
      setFailedPosts(postsData);

      // Fetch logs
      const logsRes = await fetch(`${API_BASE}/logs?limit=50`);
      const logsData = await logsRes.json();
      setLogs(logsData);
    } catch (e) {
      console.error("Failed to fetch errors data", e);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const handleRetryAll = async () => {
    try {
      await fetch(`${API_BASE}/posts/retry-failed`, {
        method: 'POST'
      });
      fetchData(); // Refresh list after reset
    } catch (e) {
      console.error("Failed to retry posts", e);
    }
  };

  return (
    <div className="view-container animate-fade-in" style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '30px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1 className="view-title" style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <AlertOctagon size={24} color="#ef4444" /> {t("خطاها و گزارش‌ها")}</h1>
          <p style={{ color: 'var(--text-secondary)' }}>{t("دانلودهای ناموفق و رویدادهای برنامه را بررسی کنید.")}</p>
        </div>
        
        <button className="btn btn-primary" onClick={handleRetryAll} disabled={failedPosts.length === 0}>
          <RotateCw size={16} /> {t("آماده‌سازی دوبارهٔ دانلودهای ناموفق")}</button>
      </div>

      <div style={{ display: 'flex', gap: '20px' }}>
        {/* Failed Posts */}
        <div className="card" style={{ flex: 1 }}>
          <h2 style={{ fontSize: '16px', marginBottom: '15px', color: '#ef4444' }}>
            {t("دانلودهای ناموفق (")}{failedPosts.length})
          </h2>
          {failedPosts.length === 0 ? (
            <div style={{ padding: '20px', color: 'var(--text-secondary)' }}>{t("دانلود ناموفقی وجود ندارد.")}</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', maxHeight: '500px', overflowY: 'auto' }}>
              {failedPosts.map(post => (
                <div key={post.pk} style={{ padding: '10px', background: 'rgba(239, 68, 68, 0.1)', borderRadius: '4px', borderLeft: '3px solid #ef4444' }}>
                  <div style={{ fontWeight: 500 }}>{t('Post from @')}{post.owner_username}</div>
                  <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>{t('Code:')} {post.shortcode} {t('| Media Type:')} {post.media_type}</div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* System Logs */}
        <div className="card" style={{ flex: 2 }}>
          <h2 style={{ fontSize: '16px', marginBottom: '15px', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <List size={18} /> {t("رویدادهای اخیر")}</h2>
          {logs.length === 0 ? (
            <div style={{ padding: '20px', color: 'var(--text-secondary)' }}>{t("گزارشی موجود نیست.")}</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '500px', overflowY: 'auto', fontSize: '13px' }}>
              {logs.map(log => (
                <div key={log.id} style={{ display: 'flex', gap: '15px', padding: '8px', borderBottom: '1px solid var(--border)' }}>
                  <span style={{ color: 'var(--text-secondary)', minWidth: '130px' }}>{new Date(log.timestamp * 1000).toLocaleString(language === 'fa' ? 'fa-IR' : 'en-US')}</span>
                  <span style={{ color: log.level === 'ERROR' ? '#ef4444' : log.level === 'WARNING' ? '#eab308' : 'var(--text-secondary)', minWidth: '70px' }}>
                    [{t(log.level)}]
                  </span>
                  <span style={{ flex: 1 }}>{log.message}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default Errors;
