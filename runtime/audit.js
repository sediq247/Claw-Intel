import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

class AuditLogger {
  constructor(options = {}) {
    this.logDir = options.logDir || path.join(__dirname, '..', 'logs');
    this.maxFileSize = options.maxFileSize || 5 * 1024 * 1024; // 5MB
    this.maxFiles = options.maxFiles || 10;
    this.currentDate = new Date().toISOString().split('T')[0];
    this.logFile = null;
    this.eventCount = 0;
    this.errorCount = 0;

    this._ensureLogDir();
    this._openLogFile();
  }

  _ensureLogDir() {
    if (!fs.existsSync(this.logDir)) {
      fs.mkdirSync(this.logDir, { recursive: true });
    }
  }

  _openLogFile() {
    const filename = `clawintel-${this.currentDate}.log`;
    this.logFile = path.join(this.logDir, filename);
  }

  _rotateIfNeeded() {
    try {
      if (fs.existsSync(this.logFile)) {
        const stats = fs.statSync(this.logFile);
        if (stats.size > this.maxFileSize) {
          const timestamp = Date.now();
          const rotatedName = `clawintel-${this.currentDate}-${timestamp}.log`;
          fs.renameSync(this.logFile, path.join(this.logDir, rotatedName));
          this._cleanupOldFiles();
        }
      }
    } catch (err) {
      console.error('[audit] Rotation error:', err.message);
    }
  }

  _cleanupOldFiles() {
    try {
      const files = fs.readdirSync(this.logDir)
        .filter((f) => f.startsWith('clawintel-') && f.endsWith('.log'))
        .map((f) => ({
          name: f,
          path: path.join(this.logDir, f),
          time: fs.statSync(path.join(this.logDir, f)).mtime.getTime(),
        }))
        .sort((a, b) => b.time - a.time);

      if (files.length > this.maxFiles) {
        files.slice(this.maxFiles).forEach((f) => {
          fs.unlinkSync(f.path);
        });
      }
    } catch (err) {
      console.error('[audit] Cleanup error:', err.message);
    }
  }

  /**
   * Log an event
   */
  logEvent(eventType, payload, source = 'system') {
    this.eventCount++;
    const entry = {
      timestamp: new Date().toISOString(),
      level: 'EVENT',
      source,
      eventType,
      payload: this._sanitizePayload(payload),
    };
    this._write(entry);
  }

  /**
   * Log an agent decision
   */
  logDecision(agent, token, verdict, details = {}) {
    const entry = {
      timestamp: new Date().toISOString(),
      level: 'DECISION',
      source: agent,
      token,
      verdict,
      details: this._sanitizePayload(details),
    };
    this._write(entry);
  }

  /**
   * Log an error
   */
  logError(source, error, context = {}) {
    this.errorCount++;
    const entry = {
      timestamp: new Date().toISOString(),
      level: 'ERROR',
      source,
      message: error.message || String(error),
      stack: error.stack || null,
      context: this._sanitizePayload(context),
    };
    this._write(entry);
  }

  /**
   * Log a warning
   */
  logWarning(source, message, context = {}) {
    const entry = {
      timestamp: new Date().toISOString(),
      level: 'WARN',
      source,
      message,
      context: this._sanitizePayload(context),
    };
    this._write(entry);
  }

  /**
   * Log system info
   */
  logInfo(source, message, context = {}) {
    const entry = {
      timestamp: new Date().toISOString(),
      level: 'INFO',
      source,
      message,
      context: this._sanitizePayload(context),
    };
    this._write(entry);
  }

  /**
   * Write entry to log file
   */
  _write(entry) {
    try {
      this._rotateIfNeeded();
      const line = JSON.stringify(entry) + '\n';
      fs.appendFileSync(this.logFile, line);
    } catch (err) {
      console.error('[audit] Write failed:', err.message);
    }
  }

  /**
   * Sanitize payload — remove sensitive fields, truncate large data
   */
  _sanitizePayload(payload) {
    if (!payload || typeof payload !== 'object') return payload;

    const sanitized = { ...payload };
    const sensitiveKeys = ['privateKey', 'secret', 'password', 'apiKey', 'token'];

    sensitiveKeys.forEach((key) => {
      if (key in sanitized) {
        sanitized[key] = '***REDACTED***';
      }
    });

    // Truncate large string values
    Object.keys(sanitized).forEach((key) => {
      if (typeof sanitized[key] === 'string' && sanitized[key].length > 5000) {
        sanitized[key] = sanitized[key].substring(0, 5000) + '...[truncated]';
      }
    });

    return sanitized;
  }

  /**
   * Get log statistics
   */
  getStats() {
    return {
      eventCount: this.eventCount,
      errorCount: this.errorCount,
      logFile: this.logFile,
      logDir: this.logDir,
    };
  }

  /**
   * Read recent log entries
   */
  readRecent(count = 100) {
    try {
      if (!fs.existsSync(this.logFile)) return [];
      const content = fs.readFileSync(this.logFile, 'utf-8');
      const lines = content.split('\n').filter(Boolean);
      return lines.slice(-count).map((line) => JSON.parse(line));
    } catch (err) {
      console.error('[audit] Read failed:', err.message);
      return [];
    }
  }

  /**
   * Graceful shutdown
   */
  shutdown() {
    console.log('[audit] Logger shut down. Stats:', this.getStats());
  }
}

export default AuditLogger;
export { AuditLogger };