# Task Ticket Example

## Summary
Set up GitHub Actions CI/CD pipeline for automated testing and deployment

## Description

h3. Task Description

Configure GitHub Actions workflow to automatically run tests on pull requests and deploy to staging environment on merge to main branch.

h3. Context

Currently, we run tests manually before merging PRs and deploy to staging using manual scripts. This is error-prone and slows down development velocity. Automating this process will improve code quality and deployment reliability.

This task supports the infrastructure improvement epic (PROJ-100).

h3. Steps

# Create `.github/workflows/ci.yml` file
# Configure workflow to trigger on pull requests to main branch
# Add job to install dependencies using `uv`
# Add job to run linting (ruff)
# Add job to run tests (pytest with coverage)
# Add job to build Docker image
# Create `.github/workflows/deploy-staging.yml` file
# Configure workflow to trigger on push to main branch
# Add job to deploy Docker image to staging environment (AWS ECS)
# Add job to run smoke tests against staging
# Configure secrets in GitHub repository settings (AWS credentials, Docker registry)
# Test workflows with a draft PR

h3. Expected Outcome

* Pull requests automatically run CI checks (lint, test, build)
* PRs cannot be merged if CI fails
* Merging to main automatically deploys to staging
* Deployment status is visible in GitHub Actions tab
* Failed deployments send notifications to Slack channel

h3. Resources/References

* GitHub Actions documentation: https://docs.github.com/en/actions
* Existing deployment script: `scripts/deploy-staging.sh`
* AWS ECS task definition: `infrastructure/ecs/task-definition.json`
* Similar workflow in other repo: https://github.com/company/other-project/.github/workflows/ci.yml

h3. Notes

* Use GitHub's reusable workflows to avoid duplication
* Cache dependencies to speed up workflow execution
* Set timeout limits to prevent hanging workflows
* Use matrix strategy to test on multiple Python versions (3.10, 3.11, 3.12)
* Store deployment artifacts for 7 days for debugging
