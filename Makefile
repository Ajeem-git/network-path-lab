.PHONY: config build up down test baseline asymmetric failover restore status

config:
	docker compose config

build:
	docker compose build

up:
	docker compose up --build -d

down:
	docker compose down

test:
	python3 -m unittest discover -s tests -v

baseline:
	python3 app/labctl.py scenario baseline

asymmetric:
	python3 app/labctl.py scenario asymmetric

failover:
	python3 app/labctl.py scenario failover

restore:
	python3 app/labctl.py scenario restore

status:
	python3 app/labctl.py status
