---
title: Deploying FileBridge to Render
description: Learn how to deploy FileBridge on Render.
keywords: FileBridge, deployment, render, self-hosting
author: Rasul Kireev
---

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=)

## Required configuration

Before deploying, you need to configure environment variables. See the [Environment Variables](/docs/deployment/environment-variables/) guide for detailed information about all configuration options.

Refer to the [Environment Variables](/docs/deployment/environment-variables/) guide for the complete list of required and optional variables.

All other variables beyond the required ones are optional but may enhance functionality.

**Note:** This should work out of the box with Render's free tier if you provide the required configuration. Here's what you need to know about the limitations:

- **Worker Service Limitation**: The worker service is not a dedicated worker type (those are only available on paid plans). For the free tier, I had to use a web service through a small hack, but it works fine for most use cases.

- **Memory Constraints**: The free web service has a 512 MB RAM limit, which can cause issues with **automated background tasks only**. When you add a project, it runs a suite of background tasks to analyze your website, generate articles, keywords, and other content. These automated processes can hit memory limits and potentially cause failures.

- **Manual Tasks Work Fine**: However, if you perform tasks manually (like generating a single article), these typically use the web service instead of the worker and should work reliably since it's one request at a time.

- **Upgrade Recommendation**: If you do upgrade to a paid plan, use the actual worker service instead of the web service workaround for better automated task reliability.

**Reality Check**: The website functionality should be usable on the free tier - you'll only pay for API costs. Manual operations work fine, but automated background tasks (especially when adding multiple projects) may occasionally fail due to memory constraints. It's not super comfortable for heavy automated use, but perfectly functional for manual content generation.

If you know of any other services like Render that allow deployment via a button and provide free Redis, Postgres, and web services, please let me know in the [Issues](/issues) section. I can try to create deployments for those. Bear in mind that free services are usually not large enough to run this application reliably.
