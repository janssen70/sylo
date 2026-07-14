# Linux install for those running Sylo from a source clone (plan section 8,
# open decision 5: plain systemd units + venv for v1, not a .deb/.rpm/Docker
# image). Not needed for development -- see README.md's "Linux" build
# section for that; this targets a real long-running install.
#
#   sudo make install     # first install, or upgrade an existing one
#   sudo make uninstall    # stop services, remove code; keeps data + config
#   sudo make purge        # uninstall, then also remove data, config, user

PYTHON       ?= python3
OPT_DIR      := /opt/sylo
VENV_DIR     := $(OPT_DIR)/venv
DATA_DIR     := /var/lib/sylo/data
CONF_DIR     := /etc/sylo
ENV_FILE     := $(CONF_DIR)/sylo.env
UNIT_DIR     := /etc/systemd/system
SERVICE_USER := sylo
UNITS        := sylo-receiver.service sylo-webapp.service sylo-retention.service

.PHONY: install uninstall purge check-root

check-root:
	@if [ "$$(id -u)" != "0" ]; then \
		echo "must be run as root: sudo make $(MAKECMDGOALS)" >&2; \
		exit 1; \
	fi

install: check-root
	@echo "== service user =="
	getent passwd $(SERVICE_USER) >/dev/null || \
		useradd --system --no-create-home --shell /usr/sbin/nologin $(SERVICE_USER)

	@echo "== data + config directories =="
	install -d -o $(SERVICE_USER) -g $(SERVICE_USER) -m 0750 \
		$(DATA_DIR) $(DATA_DIR)/raw $(DATA_DIR)/index
	install -d -m 0755 $(CONF_DIR)

	@echo "== venv (code lives entirely under $(OPT_DIR), clone dir is disposable after this) =="
	$(PYTHON) -m venv $(VENV_DIR)
	$(VENV_DIR)/bin/pip install --upgrade pip
	$(VENV_DIR)/bin/pip install .

	@echo "== config =="
	if [ ! -f $(ENV_FILE) ]; then \
		install -m 0640 -o root -g $(SERVICE_USER) deploy/systemd/sylo.env.example $(ENV_FILE); \
		echo "wrote $(ENV_FILE) -- edit it (SYLO_ADMIN_PASSWORD) before first start"; \
	else \
		echo "$(ENV_FILE) already exists, leaving it alone"; \
	fi

	@echo "== systemd units =="
	install -m 0644 deploy/systemd/sylo-receiver.service $(UNIT_DIR)/
	install -m 0644 deploy/systemd/sylo-webapp.service $(UNIT_DIR)/
	install -m 0644 deploy/systemd/sylo-retention.service $(UNIT_DIR)/
	systemctl daemon-reload

	@echo
	@echo "Install complete. Next steps:"
	@echo "  1. Review/edit $(ENV_FILE)"
	@echo "  2. systemctl enable --now $(UNITS)"

uninstall: check-root
	-systemctl disable --now $(UNITS) 2>/dev/null
	rm -f $(UNITS:%=$(UNIT_DIR)/%)
	systemctl daemon-reload
	rm -rf $(OPT_DIR)
	@echo "Code and services removed. Data ($(DATA_DIR)) and config ($(CONF_DIR)) were kept."
	@echo "Run 'sudo make purge' to also remove those and the $(SERVICE_USER) user."

purge: uninstall
	rm -rf $(DATA_DIR) $(CONF_DIR)
	getent passwd $(SERVICE_USER) >/dev/null && userdel $(SERVICE_USER) || true
	@echo "Data, config, and service user removed."
