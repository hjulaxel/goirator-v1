#include "../game/rules.h"

#include "../external/nlohmann_json/json.hpp"

#include <sstream>

using namespace std;
using json = nlohmann::json;

Rules::Rules() {
  koRule = KO_SIMPLE;
  connectToWin = 5;
  komi = 7.5f;
}

Rules::Rules(
  int kRule,
  int connectWin,
  float km
)
  :koRule(kRule),
   connectToWin(connectWin),
   komi(km)
{}

Rules::~Rules() {
}

bool Rules::operator==(const Rules& other) const {
  return
    koRule == other.koRule &&
    connectToWin == other.connectToWin &&
    komi == other.komi;
}

bool Rules::operator!=(const Rules& other) const {
  return !(*this == other);
}


bool Rules::gameResultWillBeInteger() const {
  bool komiIsInteger = ((int)komi) == komi;
  return komiIsInteger;
}

Rules Rules::getTrompTaylorish() {
  Rules rules = Rules();
  return rules;
}


bool Rules::komiIsIntOrHalfInt(float komi) {
  return std::isfinite(komi) && komi * 2 == (int)(komi * 2);
}

set<string> Rules::koRuleStrings() {
  return {"SIMPLE"};
}

int Rules::parseKoRule(const string& s) {
  if(s == "SIMPLE") return Rules::KO_SIMPLE;
  else throw IOError("Rules::parseKoRule: Invalid ko rule: " + s);
}

string Rules::writeKoRule(int koRule) {
  if(koRule == Rules::KO_SIMPLE) return string("SIMPLE");
  return string("UNKNOWN");
}
ostream& operator<<(ostream& out, const Rules& rules) {
  out << "ko" << Rules::writeKoRule(rules.koRule);
  out << "conn" << rules.connectToWin;
  out << "komi" << rules.komi;
  return out;
}

string Rules::toString() const {
  ostringstream out;
  out << (*this);
  return out.str();
}


json Rules::toJson() const {
  json ret;
  ret["ko"] = writeKoRule(koRule);
  ret["conn"] = connectToWin;
  ret["komi"] = komi;
  return ret;
}

Hash128 Rules::getRuleHashExceptKomi() const {
  Hash128 hash = Rules::ZOBRIST_KO_RULE_HASH[koRule];
  if(connectToWin > 0) {
    hash ^= Hash128(
      Hash::rrmxmx(connectToWin * ZOBRIST_CONNECT_TO_WIN_HASH.hash0),
      Hash::rrmxmx(connectToWin * ZOBRIST_CONNECT_TO_WIN_HASH.hash1));
  }
  return hash;
}


string Rules::toJsonString() const {
  return toJson().dump();
}


Rules Rules::updateRules(const string& k, const string& v, Rules oldRules) {
  Rules rules = oldRules;
  string key = Global::trim(k);
  string value = Global::trim(Global::toUpper(v));
  if(key == "ko") rules.koRule = Rules::parseKoRule(value);
  else if(key == "conn") {
    int va = Global::stringToInt(value);
    if(va < 0 || va > 19)
      throw IOError("Bad conn rules option: value should be between 0 and 19");
    rules.connectToWin = va;
  }
  else throw IOError("Unknown rules option: " + key);
  return rules;
}

static Rules parseRulesHelper(const string& sOrig, bool allowKomi) {
  Rules rules = Rules();
  string lowercased = Global::trim(Global::toLower(sOrig));
  if(lowercased == "chinese" || lowercased == "tromp-taylor" || lowercased == "tromp_taylor" ||
     lowercased == "tromp taylor" || lowercased == "tromptaylor") {
    rules.koRule = Rules::KO_SIMPLE;
    rules.komi = 7.5;
  }
  else if(sOrig.length() > 0 && sOrig[0] == '{') {
    //Default if not specified
    rules = Rules::getTrompTaylorish();
    try {
      json input = json::parse(sOrig);
      for(json::iterator iter = input.begin(); iter != input.end(); ++iter) {
        string key = iter.key();
        if(key == "ko")
          rules.koRule = Rules::parseKoRule(iter.value().get<string>());
        else if(key == "komi") {
          if(!allowKomi)
            throw IOError("Unknown rules option: " + key);
          rules.komi = iter.value().get<float>();
          if(rules.komi < Rules::MIN_USER_KOMI || rules.komi > Rules::MAX_USER_KOMI || !Rules::komiIsIntOrHalfInt(rules.komi))
            throw IOError("Komi value is not a half-integer or is too extreme");
        }
        else if(key == "conn") {
          int v = iter.value().get<int>();
          if(v < 0 || v > 19)
            throw IOError("Bad conn rules option: value should be between 0 and 19");
          rules.connectToWin = v;
        }
        else
          throw IOError("Unknown rules option: " + key);
      }
    }
    catch(nlohmann::detail::exception&) {
      throw IOError("Could not parse rules: " + sOrig);
    }
  }

  //Legacy internal format
  else {
    auto startsWithAndStrip = [](string& str, const string& prefix) {
      bool matches = str.length() >= prefix.length() && str.substr(0,prefix.length()) == prefix;
      if(matches)
        str = str.substr(prefix.length());
      str = Global::trim(str);
      return matches;
    };

    rules = Rules::getTrompTaylorish();

    string s = sOrig;
    s = Global::trim(s);

    if(s.length() <= 0)
      throw IOError("Could not parse rules: " + sOrig);

    while(true) {
      if(s.length() <= 0)
        break;

      if(startsWithAndStrip(s,"komi")) {
        if(!allowKomi)
          throw IOError("Could not parse rules: " + sOrig);
        int endIdx = 0;
        while(endIdx < s.length() && !Global::isAlpha(s[endIdx]) && !Global::isWhitespace(s[endIdx]))
          endIdx++;
        float komi;
        bool suc = Global::tryStringToFloat(s.substr(0,endIdx),komi);
        if(!suc)
          throw IOError("Could not parse rules: " + sOrig);
        if(!std::isfinite(komi) || komi > 1e5 || komi < -1e5)
          throw IOError("Could not parse rules: " + sOrig);
        rules.komi = komi;
        s = s.substr(endIdx);
        s = Global::trim(s);
        continue;
      }
      if(startsWithAndStrip(s,"conn")) {
        int endIdx = 0;
        while(endIdx < s.length() && !Global::isAlpha(s[endIdx]) && !Global::isWhitespace(s[endIdx]))
          endIdx++;
        int v;
        bool suc = Global::tryStringToInt(s.substr(0, endIdx), v);
        if(!suc)
          throw IOError("Could not parse rules: " + sOrig);
        if(v < 0 || v > 19)
          throw IOError("Bad conn rules option: value should be between 0 and 19");
        rules.connectToWin = v;
        s = s.substr(endIdx);
        s = Global::trim(s);
        continue;
      }
      if(startsWithAndStrip(s,"ko")) {
        if(startsWithAndStrip(s,"SIMPLE")) rules.koRule = Rules::KO_SIMPLE;
        else throw IOError("Could not parse rules: " + sOrig);
        continue;
      }

      //Unknown rules format
      else throw IOError("Could not parse rules: " + sOrig);
    }
  }

  return rules;
}

Rules Rules::parseRules(const string& sOrig) {
  return parseRulesHelper(sOrig,true);
}

bool Rules::tryParseRules(const string& sOrig, Rules& buf) {
  Rules rules;
  try { rules = parseRulesHelper(sOrig,true); }
  catch(const StringError&) { return false; }
  buf = rules;
  return true;
}


const Hash128 Rules::ZOBRIST_KO_RULE_HASH[2] = {
  Hash128(0x3cc7e0bf846820f6ULL, 0x1fb7fbde5fc6ba4eULL),  //Based on sha256 hash of Rules::KO_SIMPLE
  Hash128(0xcc18f5d47188554aULL, 0x3a63152c23e4128dULL),  //Based on sha256 hash of Rules::KO_POSITIONAL
};

const Hash128 Rules::ZOBRIST_CONNECT_TO_WIN_HASH =
  Hash128(0xa7d3c1e8f4b25609ULL, 0x2e8f6a1d09c47b3eULL);
