# Story Ticket Example

## Summary
Step-by-step questionnaire navigation and progress tracking

## Description

h3. User Story

As a *user*, I want to navigate through a step-by-step questionnaire with clear progress indication, so that I can easily track my completion status and move between sections.

h3. Acceptance Criteria

h4. 1. Navigation Controls

* Previous and Next buttons appear on each step
* Previous button is disabled on first step
* Next button is disabled on last step
* Submit button appears only on final step
* Keyboard navigation works (Enter for Next, Shift+Enter for Previous)

h4. 2. Progress Indicator

* Progress bar displays at top of questionnaire
* Shows percentage completion (0-100%)
* Updates in real-time as user advances
* Displays "Step X of Y" text below progress bar
* Each completed step is visually marked (checkmark icon)

h4. 3. Step Validation

* Cannot proceed to next step until current step is valid
* Invalid fields are highlighted in red
* Error messages appear below invalid fields
* Submit button is disabled until all steps are valid

h4. 4. State Persistence

* Progress is saved after each step completion
* User can safely close browser and resume later
* Navigating back to previous steps preserves entered data
* Clear warning before abandoning incomplete questionnaire

h3. Technical Notes

* *Component/File*: `src/components/Questionnaire/Navigation.tsx`, `src/components/Questionnaire/ProgressBar.tsx`
* *State management*: Use React Context for questionnaire state
* *Validation*: Integrate with existing form validation library (Zod)
* *Persistence*: Store progress in localStorage with project ID as key
* *API endpoints*: None required for this story (client-side only)

h3. Definition of Done

* All acceptance criteria met
* Unit tests written for navigation logic
* E2E tests cover complete questionnaire flow
* Progress persistence tested across browser refresh
* Responsive design works on mobile (320px+) and desktop
* Code reviewed and approved
* Documentation updated in Storybook
