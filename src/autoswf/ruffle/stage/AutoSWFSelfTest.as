package {
    import flash.display.DisplayObject;
    import flash.display.MovieClip;
    import flash.events.Event;
    import flash.geom.Matrix;
    import flash.geom.Rectangle;
    import flash.utils.getQualifiedClassName;

    /** The stage's self-test (flashvar selftest=1). Each check is traced as
     *  "AUTOSWF CHECK <name> | <PASS | FAIL detail | SKIP why>", then "AUTOSWF DONE"; tests/ruffle_selftest.py reads
     *  them from Ruffle's output. Steps run one per frame and wait for the stage where they must. */
    public class AutoSWFSelfTest {
        private var stage:AutoSWFStage;
        private var steps:Array = [];
        private var waited:int = 0;
        private var skill:Object;
        private var frame0:int;
        private var label0:String;
        private var x0:Number;

        public function AutoSWFSelfTest(stage:AutoSWFStage) {
            this.stage = stage;
        }

        public function start():void {
            steps.push(waitListeners, replayIdle, wait(3), checkSetup, playSkill, waitSkill, waitIdle, wait(3),
                checkReturned, checkWindow,
                startMotion, wait(2), playIdleAfterMotion, wait(3), checkMotionThenIdle, startPause, checkPause,
                waitIdle2, startWalk, wait(3), checkWalk, waitArrive, startDummy, waitInRange, waitHit,
                startHeadTrack, wait(2), checkHeadTrack, done);
            stage.addEventListener(Event.ENTER_FRAME, onFrame);
        }

        /** Once the listeners exist, Idle again, as the game sends its next label: the armor's own Idle handler runs
         *  (it was not registered yet when the avatar first played Idle). */
        private function replayIdle():Boolean {
            if (stage.face != null) stage.playGameLabel("Idle");
            return true;
        }

        /** Frame-script armors (Azrael) register their game labels when their head reaches frame 2. */
        private function waitListeners():Boolean {
            if (stage.face == null) return ++waited >= 2;
            for (var label:String in stage.avatar.animEvents) return ++waited >= 2;
            return ++waited >= 40;
        }

        private function onFrame(e:Event):void {
            while (steps.length > 0) {
                var finished:Boolean = steps[0]();
                if (!finished) return;
                steps.shift();
                waited = 0;
            }
            stage.removeEventListener(Event.ENTER_FRAME, onFrame);
        }

        private function check(name:String, ok:Boolean, detail:String = ""):void {
            stage.log("CHECK " + name + " | " + (ok ? "PASS" : "FAIL " + detail));
        }

        private function skip(name:String, why:String):void {
            stage.log("CHECK " + name + " | SKIP " + why);
        }

        private function wait(frames:int):Function {
            return function ():Boolean { return ++waited >= frames; };
        }

        private function animationOf(game:String):String {
            var r:Object = stage.rowOf(game);
            return r == null ? null : r.armor[stage.gender];
        }

        private function frameOf():int {
            var body:MovieClip = stage.face.getChildByName("body") as MovieClip;
            return body != null ? body.currentFrame : stage.face.currentFrame;
        }

        private function totalOf():int {
            var body:MovieClip = stage.face.getChildByName("body") as MovieClip;
            return body != null ? body.totalFrames : stage.face.totalFrames;
        }

        // ------------------------------------------------------------ the avatar (Task 3)

        private function checkSetup():Boolean {
            if (stage.face == null) {                   // the head could not be made: report it and stop there
                stage.updateStatus();
                check("ui", stage.status.parent == stage && stage.list != null && stage.bar != null, "no status, list or bar");
                if (stage.armorError == null) check("armor error shown", false, "no head and no error");
                else check("armor error shown", stage.status.text.indexOf(stage.armorError) >= 0, stage.status.text);
                steps.splice(1, steps.length - 2);
                return true;
            }
            var count:int = 0;
            for (var label:String in stage.avatar.animEvents) count++;
            check("listeners", count > 0, "the armor registered no game label");
            var idle:String = animationOf("Idle");
            var face:MovieClip = stage.face;
            if (idle == null) skip("idle", "the armor does not take Idle");
            else check("idle", face != null && face.currentLabel == idle, face == null ? "no head" : face.currentLabel);
            if (face == null || face.transform.matrix.a == 1 && face.transform.matrix.d == 1 &&
                    face.transform.matrix.tx == 0 && face.transform.matrix.ty == 0) {
                skip("anchored", "the armor does not anchor itself");
            } else {
                var m:Matrix = face.transform.matrix.clone();
                m.concat(stage.avatar.mcChar.head.transform.matrix);
                var near:Function = function (a:Number, b:Number, by:Number):Boolean { return Math.abs(a - b) < by; };
                // positions are kept in twips (1/20 px) by the player
                check("anchored", near(m.a, 1, 0.01) && near(m.b, 0, 0.01) && near(m.c, 0, 0.01) &&
                    near(m.d, 1, 0.01) && near(m.tx, 0, 0.1) && near(m.ty, 0, 0.1), m.toString());
            }
            if (stage.avatar.mcChar.head.hair.visible) skip("hair hidden", "the armor shows the avatar's hair");
            else check("hair hidden", true);
            var probe:MovieClip = new MovieClip();
            var before:uint = uint(stage.colors.Hair);
            stage.mcSetColor(probe, "Hair", "None");
            stage.setPlayerColor("Hair", 0x123456);
            check("color Hair", probe.transform.colorTransform.color == 0x123456,
                probe.transform.colorTransform.color.toString(16));
            stage.setPlayerColor("Hair", before);
            check("ui", stage.status.parent == stage && stage.list != null && stage.bar != null, "no status, list or bar");
            if (stage.armorError == null) skip("armor error shown", "the armor's code did not stop");
            else check("armor error shown", stage.status.text.indexOf(stage.armorError) >= 0, stage.status.text);
            return true;
        }

        private function playSkill():Boolean {
            var slots:Array = stage.settings.skills[stage.gender] as Array;
            skill = slots != null && slots.length > 0 ? slots[0] : null;
            if (skill == null || skill.armor == null) {
                skill = null;
                skip("skill", "the armor takes no skill label");
                return true;
            }
            stage.avatar.playLabel(skill.game);
            return true;
        }

        private function waitSkill():Boolean {
            if (skill == null) return true;
            if (stage.face.currentLabel == skill.armor) {
                check("skill " + skill.game, true);
                return true;
            }
            if (++waited < 3) return false;
            check("skill " + skill.game, false, "the head is on " + stage.face.currentLabel);
            skill = null;
            return true;
        }

        private var returned:Boolean = false;

        private function waitIdle():Boolean {
            if (skill == null) return true;
            if (stage.face.currentLabel == animationOf("Idle")) {
                check("back to Idle", true);
                returned = true;
                return true;
            }
            if (++waited < 300) return false;
            check("back to Idle", false, "still on " + stage.face.currentLabel + " after 300 frames");
            return true;
        }

        /** The armor went back to Idle by itself: the status says so, and a step back stays on Idle. */
        private function checkReturned():Boolean {
            if (!returned) {
                skip("status follows the head", "the armor did not go back to Idle by itself");
                skip("step back after the armor returns", "the armor did not go back to Idle by itself");
                return true;
            }
            stage.updateStatus();
            var idle:String = animationOf("Idle");
            check("status follows the head", stage.status.text.indexOf(skill.game) != 0 &&
                stage.status.text.indexOf(idle) >= 0, stage.status.text);
            stage.togglePause();
            var f0:int = frameOf();
            stage.playback.step(1);
            stage.playback.step(-1);
            check("step back after the armor returns", stage.face.currentLabel == idle && frameOf() == f0,
                stage.face.currentLabel + " frame " + frameOf() + ", expected " + idle + " frame " + f0);
            stage.togglePause();
            return true;
        }

        /** An armor animation by name, then a game label: the armor's code starts afresh and plays it. */
        private function startMotion():Boolean {
            if (skill != null) stage.playMotion(skill.armor);
            return true;
        }

        private function playIdleAfterMotion():Boolean {
            if (skill != null) stage.playGameLabel("Idle");
            return true;
        }

        private function checkMotionThenIdle():Boolean {
            var idle:String = animationOf("Idle");
            if (skill == null || idle == null) skip("motion then Idle", "the armor takes no skill label or Idle");
            else check("motion then Idle", stage.face.currentLabel == idle, "head on " + stage.face.currentLabel);
            return true;
        }

        // ------------------------------------------------------------ the window (Task 4)

        private function inside(o:DisplayObject):Boolean {
            var r:Rectangle = o.getBounds(stage);
            return r.left >= -1 && r.top >= -1 && r.right <= AutoSWFStage.W + 1 && r.bottom <= AutoSWFStage.H + 1;
        }

        private function checkWindow():Boolean {
            var motions:Array = stage.settings.motions[stage.gender] as Array;
            var expected:int = stage.settings.labels.length + (motions == null ? 0 : motions.length);
            check("list rows", stage.list.rows.length == expected, stage.list.rows.length + " rows, " + expected +
                " expected");
            stage.list.scrollTo(stage.list.rows.length - 1);
            check("list scrolls to end", stage.list.rowVisible(stage.list.rows.length - 1), "last row hidden");
            var last:int = stage.list.rows.length - 1;
            stage.list.scrollFraction(0);
            var top:Boolean = stage.list.rowVisible(0);
            stage.list.scrollFraction(1);
            var bottom:Boolean = stage.list.rowVisible(last);
            stage.list.scrollFraction(0);
            var tall:Boolean = !stage.list.rowVisible(last);
            stage.list.page(1);
            check("list scrollbar", top && bottom && (!tall || !stage.list.rowVisible(0) && stage.list.thumb.visible),
                "top " + top + ", bottom " + bottom + ", taller than the list " + tall);
            stage.list.scroll(100000);
            var out:Array = [];
            for each (var o:DisplayObject in [stage.status, stage.controls, stage.bar, stage.list.area, stage.palette]) {
                if (!inside(o)) out.push(o.name + " " + o.getBounds(stage));
            }
            check("nothing off window", out.length == 0, out.join("; "));
            var scale:Number = stage.actors.scaleX;
            stage.zoomBy(1);
            var zoomed:Boolean = stage.actors.scaleX > scale;
            stage.zoomBy(-1);
            check("zoom", zoomed && stage.actors.scaleX == scale, "scale " + stage.actors.scaleX);
            var b:int = stage.background;
            stage.cycleBackground();
            var changed:Boolean = stage.background != b;
            for (var i:int = 1; i < AutoSWFStage.BACKGROUNDS.length; i++) stage.cycleBackground();
            check("background", changed && stage.background == b, "background " + stage.background);
            var genders:Array = stage.settings.genders;
            if (genders.length < 2) {
                check("gender switch", stage.genderButtons.length == 0, "a switch shows for one gender");
            } else {
                var first:String = stage.gender;
                stage.setGender(genders[1]);
                var swapped:Boolean = getQualifiedClassName(stage.face).indexOf(genders[1] + "Head") >= 0;
                stage.setGender(first);
                check("gender switch", stage.genderButtons.length == 2 && swapped &&
                    getQualifiedClassName(stage.face).indexOf(first + "Head") >= 0, getQualifiedClassName(stage.face));
            }
            return true;
        }

        /** Start the skill and let one frame play, then checkPause pauses it in the middle. */
        private function startPause():Boolean {
            if (skill == null) return true;
            if (waited == 0) stage.playGameLabel(skill.game);
            return ++waited >= 2;
        }

        private function checkPause():Boolean {
            if (skill == null) {
                skip("pause holds", "the armor takes no skill label");
                return true;
            }
            if (waited == 0) {
                stage.togglePause();
                frame0 = frameOf();
                label0 = stage.face.currentLabel;
                waited++;
                return false;
            }
            if (++waited < 6) return false;
            check("pause holds", frameOf() == frame0 && stage.face.currentLabel == label0,
                stage.face.currentLabel + " frame " + frameOf() + ", paused on " + label0 + " frame " + frame0);
            var total:int = totalOf();
            stage.playback.step(1);
            var expected:int = frame0 >= total ? 1 : frame0 + 1;
            check("step +1", frameOf() == expected, "frame " + frameOf() + ", expected " + expected);
            stage.playback.step(-1);
            check("step -1", frameOf() == frame0, "frame " + frameOf() + ", expected " + frame0);
            stage.togglePause();
            return true;
        }

        private function waitIdle2():Boolean {
            if (skill == null || stage.face.currentLabel == animationOf("Idle")) return true;
            return ++waited >= 300;
        }

        private function startWalk():Boolean {
            stage.dummy.selected = false;
            x0 = stage.avatar.x;
            stage.avatar.walkTo(x0 + 60, stage.avatar.y);
            return true;
        }

        private function checkWalk():Boolean {
            var walk:String = animationOf("Walk");
            check("walk", stage.avatar.x > x0 && stage.avatar.walking && (walk == null || stage.face.currentLabel == walk),
                "x " + stage.avatar.x + " from " + x0 + ", head on " + stage.face.currentLabel);
            return true;
        }

        private function waitArrive():Boolean {
            if (stage.avatar.walking && ++waited < 120) return false;
            var idle:String = animationOf("Idle");
            check("arrive Idle", !stage.avatar.walking && (idle == null || stage.face.currentLabel == idle) &&
                stage.current.name == "Idle", "walking " + stage.avatar.walking + ", head on " +
                stage.face.currentLabel + ", playing " + stage.current.name);
            return true;
        }

        private function startDummy():Boolean {
            if (skill == null) return true;
            stage.dummy.selected = true;
            stage.avatar.x = stage.dummy.x - 400;
            stage.avatar.face(-1);
            stage.useSkill(skill.game);
            return true;
        }

        private var hits0:int;

        private function waitInRange():Boolean {
            if (skill == null) {
                skip("walks into range", "the armor takes no skill label");
                return true;
            }
            if (stage.face.currentLabel != skill.armor && ++waited < 200) return false;
            var dx:Number = stage.dummy.x - stage.avatar.x;
            check("walks into range", stage.face.currentLabel == skill.armor && Math.abs(dx) <= AutoSWFStage.RANGE,
                "head on " + stage.face.currentLabel + ", " + Math.round(Math.abs(dx)) + " px from the dummy");
            check("faces target", (stage.avatar.mcChar.scaleX > 0) == (dx > 0), "scaleX " + stage.avatar.mcChar.scaleX);
            hits0 = stage.dummy.hits;
            return true;
        }

        private function waitHit():Boolean {
            if (skill == null) return true;
            if (stage.dummy.hits <= hits0 && ++waited < AutoSWFStage.HIT_DELAY + 6) return false;
            check("dummy hit", stage.dummy.hits > hits0, "no hit after " + waited + " frames");
            if (stage.settings.dummy == null) skip("dummy original", "AQW's Training Dummy is not in the cache");
            else check("dummy original", stage.dummy.monster != null && stage.dummy.monster.currentLabel == "Hit",
                stage.dummy.monster == null ? "not loaded" : "on " + stage.dummy.monster.currentLabel);
            stage.dummy.selected = false;
            return true;
        }

        // ------------------------------------------------------------ the skeleton's head placement (spec §5.4)

        private var tracked:String;

        /** A game label the armor does not block plays on the skeleton: its head slot must follow the real one. */
        private function startHeadTrack():Boolean {
            tracked = null;
            for each (var row:Object in stage.settings.labels) {
                var track:Object = stage.settings.head[stage.gender][row.name];
                if (track == null || row.group == "Skills" || row.armor[stage.gender] != null && row.block[stage.gender]) {
                    continue;
                }
                tracked = row.name;
                break;
            }
            if (tracked != null) stage.playGameLabel(tracked);
            return true;
        }

        private function checkHeadTrack():Boolean {
            if (tracked == null) {
                skip("head follows the skeleton", "the armor takes every game label of the skeleton");
                return true;
            }
            var want:Array = stage.avatar.mcChar.expectedPlacement();
            var m:Matrix = stage.avatar.mcChar.head.transform.matrix;
            var ok:Boolean = want != null && Math.abs(m.a - want[0]) < 0.01 && Math.abs(m.b - want[1]) < 0.01 &&
                Math.abs(m.c - want[2]) < 0.01 && Math.abs(m.d - want[3]) < 0.01 && Math.abs(m.tx - want[4]) < 0.1 &&
                Math.abs(m.ty - want[5]) < 0.1;
            check("head follows the skeleton", ok, tracked + ": " + m + " vs " + want);
            return true;
        }

        private function done():Boolean {
            stage.log("DONE");
            return true;
        }
    }
}
