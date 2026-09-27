# AgriMon · Prompt examples

These prompts ran successfully in AgriMon Evolution 1 (contract v2) on the two bundled USGS EROS
true-color scenes. Every answer passed all 18 blocking harness checks. "Existing" means the
question was answered by a capability already in the registry; "new" means AgriMon generated,
evaluated and committed a new capability to answer it.

## Recommended examples

These produce clear, well-grounded answers and are the best ones to show.

|Prompt|Scene|Path|Capability|What you get|
|-|-|-|-|-|
|Give me a brightness overview of this image|Forested valley|Existing (seed)|`rgb\_overview`|Brightness matrix (yellow–red), brightest and darkest zones outlined, mean 0.352 with range 0.206–0.615|
|Can you check where the vegetation is unusually low?|Forested valley|New|`vegetation\_proxy\_rgb`|RGB vegetation proxy matrix (greens); low values mark sparse vegetation|
|Show me the vegetation intensity across this field.|Forested valley|Existing|`vegetation\_proxy\_rgb`|Same capability reused, no generation|
|where all does the vegetation appear in the image..|Reservoir and farmland|Existing|`vegetation\_proxy\_rgb`|Reused on the other scene; values go negative over water (minimum −0.065)|
|Vegetation hotspots and coldspots|Forested valley|New|`vegetation\_hotspots\_rgb`|Vegetation index matrix (greens), mean 0.143, highlighting high and low areas|
|Analyze the water body variation|Reservoir and farmland|New|`water\_body\_variation\_rgb`|Water variation index (blues), mean 0.192, with a next step to inspect high-variation areas|
|Can you find barren land areas ?|Forested valley, then reservoir|New, then existing|`barren\_land\_identification\_rgb`|Barren-land score (yellow–red), created on one scene and reused on the other|

## Reuse in action

Asking related questions in this order shows the registry growing and then being reused:

1. "Can you check where the vegetation is unusually low?" creates `vegetation\_proxy\_rgb`.
2. "Show me the vegetation intensity across this field." reuses it on the same scene.
3. "where all does the vegetation appear in the image.." reuses it on the other scene.
4. "Can you find barren land areas ?" creates `barren\_land\_identification\_rgb` on the forested valley,
and the same question on the reservoir scene reuses it.

## Also successful, with caveats

These passed every blocking check, but the output needs a careful read before being shown.

|Prompt|Scene|Path|Capability|Caveat|
|-|-|-|-|-|
|Can you identify non farm lands in the image?|Forested valley|New|`non\_farm\_land\_identification\_rgb`|Classified map (farm 16%, non-farm 84%) is useful, but one finding says "2304 cells" of non-farm land, which is the total cell count, not the 1,924 non-farm cells|
|Analyze and categorize all farm lands|Reservoir and farmland|New (third candidate)|`farm\_land\_identification\_rgb`|Classified map (farm 83%, non-farm 17%) is useful, but one finding shows an unfilled placeholder instead of a number|
|Soil moisture analysis based on the vegetation information?|Forested valley|New|`soil\_moisture\_proxy\_rgb`|A true-color image cannot measure soil moisture; the result is a proxy inferred from greenness and should be labelled that way|
|Rainfall impact on soil based on the chlorophyll green|Forested valley|New|`chlorophyll\_impact\_rgb`|Returns a green-band ratio (mean 0.400); it says nothing about rainfall, which the scene cannot show|
|Can you find barren land areas ? (asked first on the reservoir scene)|Reservoir and farmland|Existing|`non\_farm\_land\_identification\_rgb`|Before a barren-land capability existed, the intent resolver mapped this to the non-farm land capability; the answer is a farm/non-farm map, not barren land|



* Ask about what a true-color image can show: brightness, greenness, water, bare or barren ground,
land-cover classes. Near-infrared indices such as NDVI need bands these scenes do not have.
* Say "categorize" or "identify … areas" when you want a classified map; otherwise the answer is a
continuous layer.
* Reusing wording from an earlier question, or asking the same thing on the other scene, shows the
match path.

