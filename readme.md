# Optifine Account Checker

A simple Selenium-based checker for [optifine.net](https://optifine.net) accounts. It reads email:password pairs from a file, attempts to log in to each one, and saves the results into separate files based on whether the credentials are valid or not.

## How It Works

1. **Reads `accounts.txt`** – The script loads all lines from `accounts.txt` in the same folder. Each line must be in the format `email:password`.
2. **Opens the browser** – Uses [SeleniumBase](https://github.com/seleniumbase/SeleniumBase) in UC (undetected) CDP mode with guest mode enabled, so it runs without requiring a full Chrome profile.
3. **Logs in** – For every account, it navigates to `https://optifine.net/login`, fills in the email and password fields, and submits the form.
4. **Checks the result** – After login, it waits for an `h2` element to appear. If the heading contains the word `Capes`, the account is considered **valid**. Otherwise it's marked as **invalid**.
5. **Saves the result**:
   - Valid accounts → appended to `valid.txt`
   - Invalid accounts → appended to `invalid.txt`
6. **Removes the processed line** – Every account that has been checked is removed from `accounts.txt`, so the script can be resumed later without re-checking the same accounts.

## Requirements

- Python 3.8+
- [SeleniumBase](https://github.com/seleniumbase/SeleniumBase) (`pip install seleniumbase`)
- A Chromium-based browser installed (SeleniumBase will download one automatically if needed)

## File Structure
