module.exports = {
  apps: [{
    name: 'reze-addon',
    script: 'addon_daemon.py',
    cwd: '/home/reze/reze-agent/addon',
    interpreter: '/home/reze/reze-agent/addon/.venv/bin/python3',
    autorestart: true,
    watch: false,
    max_memory_restart: '500M',
    env: {
      REZE_HOME: '/home/reze/reze-agent',
      REZE_SSOT_DB: '/home/reze/reze-agent/reze.db',
      REZE_ADDON_DB: '/home/reze/reze-agent/addon/data/addon.db'
    },
    log_date_format: 'YYYY-MM-DD HH:mm:ss',
    error_file: '/home/reze/reze-agent/addon/logs/pm2-error.log',
    out_file: '/home/reze/reze-agent/addon/logs/pm2-out.log'
  }]
};
