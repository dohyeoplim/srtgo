<h3 align="center">
    dohyeoplim/srtgo
</h3>

<hr />

### Features

- Automatic rail service reservation with retries and waiting list.
- Card payment, cancellation, and Slack notifications.
- MCP server for AI assistants.

### Usage

#### Setup

```sh
cp .env.example .env
```

- `.env` in the working directory or environment variables.
- Required: `KORAIL_LOGIN_ID`, `KORAIL_PASSWORD`.
- Optional: `CARD_*` for payment, `SLACK_WEBHOOK_URL` for notifications.

#### CLI

```sh
pip install git+https://github.com/dohyeoplim/srtgo.git
srtgo
```

#### MCP

```sh
docker compose up -d --build
```

- URL: `http://127.0.0.1:8742/mcp`
- Header: `Authorization: Bearer <MCP_AUTH_TOKEN>`

### Disclaimer

- Commercial use is prohibited.
- Use at your own risk.

### Acknowledgments

- Forked from [lapis42/srtgo](https://github.com/lapis42/srtgo).
- Includes code from [SRT](https://github.com/ryanking13/SRT) by ryanking13 (MIT License)
  and [korail2](https://github.com/carpedm20/korail2) by carpedm20 (BSD License).
