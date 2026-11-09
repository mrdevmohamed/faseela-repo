# Documentation site

The project documentation is written in Markdown and built with Zensical. The generated static site is deployed to GitHub Pages by **.github/workflows/docs.yml**.

## Local preview

Use Python 3.11 or newer:

~~~sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-docs.txt
zensical serve
~~~

To build exactly as CI does:

~~~sh
zensical build --clean --strict
~~~

The site output is placed in **site/**. Do not commit generated output; the directory is ignored by Git.

The documentation dependency is pinned in **requirements-docs.txt**. Upgrade it deliberately and verify the strict site build before merging.

## Pull-request checks and deployment

A pull request that changes documentation, the Zensical configuration, the pinned dependency, or the docs workflow runs a strict build. Pull requests do not deploy a Pages site.

A push to **main** that changes those paths builds the site and deploys the generated artifact. The workflow uses the **github-pages** deployment environment and the permissions required by GitHub Pages.

## One-time GitHub Pages setting

The repository currently has GitHub Pages disabled. After this documentation change is merged, an administrator must enable the publishing source:

1. Open the repository **Settings**.
2. Select **Pages** under the Code and automation section.
3. Under **Build and deployment → Source**, select **GitHub Actions**.
4. Save the setting.

The next successful push to **main**, or a manual run of the Documentation workflow on **main**, will publish the site at:

~~~text
https://mrdevmohamed.github.io/faseela-repo/
~~~

The workflow cannot enable Pages by itself because that requires repository-level administration access beyond the normal workflow token. See the [GitHub Pages publishing-source guide](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site).
